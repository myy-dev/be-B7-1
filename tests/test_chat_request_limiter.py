import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from app.core.chat_request_limiter import ChatRequestLimiter
from app.core.errors import APIError
from app.models.chat import Chat, ChatLog
from app.services.chat_service import ChatService


@pytest.mark.parametrize("phase", ["history", "question", "answer", "failure"])
def test_database_failure_releases_user(phase: str) -> None:
    """문맥 조회·질문·답변·실패 저장 오류에서도 다음 질문을 승인한다."""

    async def run() -> None:
        limiter = ChatRequestLimiter(max_concurrent_requests=1)
        repository = AsyncMock()
        repository.get_by_id_and_user.return_value = Chat(user_id=1)
        repository.list_recent_completed.return_value = []
        service = ChatService(repository, limiter)
        ai = AsyncMock()
        ai.model = "test-model"
        ai.generate_answer.return_value = "답변"
        failure = OperationalError("test", {}, RuntimeError())
        if phase == "history":
            repository.list_recent_completed.side_effect = failure
        else:
            repository.save_message.side_effect = (
                [failure] if phase == "question" else [None, failure]
            )
        if phase == "failure":
            ai.generate_answer.side_effect = APIError("AI_UNAVAILABLE")
        with pytest.raises(OperationalError):
            await service.send_message(uuid4(), 1, uuid4(), "질문", ai)
        async with limiter.acquire(2):
            pass

    asyncio.run(run())


def test_user_remains_busy_until_answer_saved() -> None:
    """AI 응답 후에도 답변 저장이 끝나기 전에는 추가 질문을 거절한다."""

    async def run() -> None:
        saving = asyncio.Event()
        release = asyncio.Event()
        repository = AsyncMock()
        repository.get_by_id_and_user.return_value = Chat(user_id=1)
        repository.list_recent_completed.return_value = []

        async def save(message: ChatLog) -> None:
            message.created_at = datetime.now(UTC)
            if message.status == "completed":
                saving.set()
                await release.wait()

        repository.save_message.side_effect = save
        limiter = ChatRequestLimiter(max_concurrent_requests=1)
        service = ChatService(repository, limiter)
        ai = AsyncMock()
        ai.model = "test-model"
        ai.generate_answer.return_value = "답변"
        task = asyncio.create_task(
            service.send_message(uuid4(), 1, uuid4(), "질문", ai)
        )
        try:
            await asyncio.wait_for(saving.wait(), 2)
            with pytest.raises(APIError) as error:
                await service.send_message(uuid4(), 1, uuid4(), "중복", ai)
            assert error.value.api_code == "CHAT_BUSY"
            with pytest.raises(APIError) as error:
                await service.send_message(uuid4(), 2, uuid4(), "다른 사용자 질문", ai)
            assert error.value.api_code == "SERVER_BUSY"
            assert repository.list_recent_completed.await_count == 1
            assert ai.generate_answer.await_count == 1
        finally:
            release.set()
            await task
        async with limiter.acquire(2):
            pass

    asyncio.run(run())


@pytest.mark.parametrize("max_concurrent_requests", [0, -1])
def test_nonpositive_limit_rejected(max_concurrent_requests: int) -> None:
    """처리 가능한 질문 수가 없는 제한기 생성을 거절한다."""
    with pytest.raises(ValueError):
        ChatRequestLimiter(max_concurrent_requests=max_concurrent_requests)


def test_full_capacity_rejections_preserve_occupied_slots() -> None:
    """전체 한도와 중복 거절이 기존 점유를 해제하거나 새 자리를 쓰지 않는다."""

    async def run() -> None:
        limiter = ChatRequestLimiter(max_concurrent_requests=2)
        async with limiter.acquire(1):
            async with limiter.acquire(2):
                for user_id, code in [(1, "CHAT_BUSY"), (3, "SERVER_BUSY")]:
                    with pytest.raises(APIError) as error:
                        async with limiter.acquire(user_id):
                            pytest.fail("한도 초과 요청이 승인됐다.")
                    assert error.value.api_code == code
                with pytest.raises(APIError) as error:
                    async with limiter.acquire(2):
                        pytest.fail("기존 사용자 점유가 사라졌다.")
                assert error.value.api_code == "CHAT_BUSY"
            async with limiter.acquire(3):
                with pytest.raises(APIError) as error:
                    async with limiter.acquire(4):
                        pytest.fail("기존 전체 점유가 사라졌다.")
                assert error.value.api_code == "SERVER_BUSY"
        async with limiter.acquire(4), limiter.acquire(5):
            pass

    asyncio.run(run())
