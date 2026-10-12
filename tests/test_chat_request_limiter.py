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
        limiter = ChatRequestLimiter()
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
        async with limiter.acquire(1):
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
        limiter = ChatRequestLimiter()
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
            assert repository.list_recent_completed.await_count == 1
            assert ai.generate_answer.await_count == 1
        finally:
            release.set()
            await task
        async with limiter.acquire(1):
            pass

    asyncio.run(run())
