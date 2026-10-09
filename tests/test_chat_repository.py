"""임시 SQLite에서 논리 삭제의 소유권·조회·기록 보존·롤백을 검증한다."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, _enable_sqlite_foreign_keys
from app.models.chat import Chat, ChatLog
from app.models.user import User
from app.repositories.chat_repository import ChatRepository


@pytest.fixture
def repository_sessions(tmp_path: Path) -> Iterator[async_sessionmaker[AsyncSession]]:
    """외래키를 검사하는 테스트 전용 SQLite와 요청별 세션을 제공한다.

    Args:
        tmp_path: 테스트 DB를 저장할 임시 경로.

    Yields:
        기존 User 모델의 두 사용자가 저장된 세션 팩토리.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'repository.db'}")
    event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add_all(
                User(
                    id=user_id,
                    username=f"owner_{user_id}",
                    password_hash="test-only",
                    name="테스트 회원",
                )
                for user_id in (1, 2)
            )
            await session.commit()

    asyncio.run(prepare())
    try:
        yield sessions
    finally:
        asyncio.run(engine.dispose())


def test_soft_delete_filters_user_queries_and_keeps_other_chats(
    repository_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """삭제된 방만 사용자 조회에서 사라지고 다른 방과 소유권은 유지된다."""

    async def run() -> None:
        deleted_at = datetime(2026, 10, 9, 3, tzinfo=UTC)
        async with repository_sessions() as session:
            repository = ChatRepository(session)
            deleted = await repository.create(1)
            active = await repository.create(1)
            other = await repository.create(2)
            assert await repository.soft_delete(deleted.chat_id, 1, deleted_at)
            assert not session.in_transaction()
            assert await repository.get_by_id_and_user(deleted.chat_id, 1) is None
            assert await repository.get_by_id_and_user(active.chat_id, 1) is active
            assert await repository.get_by_id_and_user(other.chat_id, 1) is None
            assert [chat.chat_id for chat in await repository.list_by_user(1)] == [
                active.chat_id
            ]
            assert [chat.chat_id for chat in await repository.list_by_user(2)] == [
                other.chat_id
            ]

        async with repository_sessions() as session:
            stored = await session.get(Chat, deleted.chat_id)
            assert stored is not None
            assert stored.deleted_at == deleted_at
            assert stored.deleted_at.tzinfo is UTC

    asyncio.run(run())


@pytest.mark.parametrize("case", ["missing", "other_owner", "already_deleted"])
def test_soft_delete_unmatched_rows_do_not_change_data(
    repository_sessions: async_sessionmaker[AsyncSession], case: str
) -> None:
    """없는 방·다른 소유자·재삭제의 갱신은 실패하고 최초 삭제 시각을 유지한다."""

    async def run() -> None:
        deleted_at = datetime(2026, 10, 9, 3, tzinfo=UTC)
        async with repository_sessions() as session:
            repository = ChatRepository(session)
            chat = await repository.create(1)
            if case == "already_deleted":
                assert await repository.soft_delete(chat.chat_id, 1, deleted_at)
            assert not await repository.soft_delete(
                uuid4() if case == "missing" else chat.chat_id,
                2 if case == "other_owner" else 1,
                deleted_at + timedelta(seconds=1),
            )
            assert not session.in_transaction()

        async with repository_sessions() as session:
            stored = await session.get(Chat, chat.chat_id)
            assert stored is not None
            assert stored.deleted_at == (
                deleted_at if case == "already_deleted" else None
            )

    asyncio.run(run())


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_pending_message_finishes_after_soft_delete(
    repository_sessions: async_sessionmaker[AsyncSession], status: str
) -> None:
    """다른 요청이 방을 삭제해도 진행 중 질문의 성공·실패 저장은 완료된다."""

    async def run() -> None:
        deleted_at = datetime(2026, 10, 9, 3, tzinfo=UTC)
        async with repository_sessions() as processing:
            repository = ChatRepository(processing)
            chat = await repository.create(1)
            message = ChatLog(
                request_id=uuid4(),
                chat_id=chat.chat_id,
                question="처리 중 질문",
                model="test-model",
            )
            await repository.save_message(message)
            async with repository_sessions() as deleting:
                assert await ChatRepository(deleting).soft_delete(
                    chat.chat_id, 1, deleted_at
                )
            message.status = status
            message.answer = "완성 답변" if status == "completed" else None
            message.error_code = "AI_TIMEOUT" if status == "failed" else None
            message.finished_at = deleted_at + timedelta(seconds=1)
            await repository.save_message(message)

        async with repository_sessions() as session:
            repository = ChatRepository(session)
            stored_chat = await session.get(Chat, chat.chat_id)
            assert stored_chat is not None
            assert stored_chat.deleted_at == deleted_at
            assert await repository.get_by_id_and_user(chat.chat_id, 1) is None
            stored_message = await session.get(ChatLog, message.request_id)
            assert stored_message is not None
            assert stored_message.question == "처리 중 질문"
            assert stored_message.status == status
            assert stored_message.answer == message.answer
            assert stored_message.error_code == message.error_code
            assert stored_message.finished_at == message.finished_at

    asyncio.run(run())


def test_soft_delete_commit_failure_rolls_back_and_session_remains_usable(
    repository_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """커밋 실패 뒤 삭제 시각을 롤백하고 같은 세션에서 다시 삭제할 수 있다."""

    async def run() -> None:
        deleted_at = datetime(2026, 10, 9, 3, tzinfo=UTC)
        async with repository_sessions() as session:
            repository = ChatRepository(session)
            chat_id = (await repository.create(1)).chat_id
            failure = OperationalError("test-only", {}, RuntimeError())
            with patch.object(session, "commit", AsyncMock(side_effect=failure)):
                with pytest.raises(OperationalError):
                    await repository.soft_delete(chat_id, 1, deleted_at)
            assert not session.in_transaction()
            chat = await repository.get_by_id_and_user(chat_id, 1)
            assert chat is not None
            assert chat.deleted_at is None
            assert await repository.soft_delete(chat_id, 1, deleted_at)

    asyncio.run(run())


def test_concurrent_soft_deletes_only_store_one_timestamp(
    repository_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """동시에 두 요청이 삭제해도 한 번만 갱신하고 최초 시각을 유지한다."""

    async def run() -> None:
        async with repository_sessions() as session:
            chat_id = (await ChatRepository(session).create(1)).chat_id
        timestamps = [
            datetime(2026, 10, 9, 3, tzinfo=UTC),
            datetime(2026, 10, 9, 4, tzinfo=UTC),
        ]

        async def delete(deleted_at: datetime) -> bool:
            async with repository_sessions() as session:
                return await ChatRepository(session).soft_delete(chat_id, 1, deleted_at)

        results = await asyncio.gather(*(delete(value) for value in timestamps))
        assert results.count(True) == 1
        async with repository_sessions() as session:
            chat = await session.get(Chat, chat_id)
            assert chat is not None
            assert chat.deleted_at == timestamps[results.index(True)]

    asyncio.run(run())
