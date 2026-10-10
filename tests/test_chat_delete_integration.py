import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import pytest
from httpx import ASGITransport, AsyncClient, Response
from openai import AsyncOpenAI
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.database import Base, _enable_sqlite_foreign_keys, get_db
from app.core.security import create_access_token
from app.main import app, lifespan
from app.models.chat import Chat, ChatLog
from app.models.user import User
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import MessageResponse


@dataclass
class _DeleteApp:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    request_sessions: list[AsyncSession]
    sdk_requests: list[httpx2.Request]
    database_url: str


@asynccontextmanager
async def _delete_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[[httpx2.Request], Awaitable[httpx2.Response]],
) -> AsyncIterator[_DeleteApp]:
    """실제 앱·JWT 인증·SDK와 임시 파일 DB를 연결한다."""
    settings = Settings(
        _env_file=None,
        openai_api_key="test-only",
        openai_model="test-model",
        ai_timeout_seconds=30,
        ai_max_retries=0,
        jwt_secret_key="test-only-chat-delete-secret-123456789",
    )
    monkeypatch.setattr("app.main.settings", settings)
    monkeypatch.setattr("app.core.security.get_settings", lambda: settings)
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'delete.db'}"
    engine = create_async_engine(database_url)
    event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    request_sessions: list[AsyncSession] = []
    sdk_requests: list[httpx2.Request] = []
    connections: list[httpx2.AsyncClient] = []

    async def create_tables() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def test_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessions() as session:
            request_sessions.append(session)
            yield session

    async def transport(request: httpx2.Request) -> httpx2.Response:
        sdk_requests.append(request)
        return await respond(request)

    def sdk_factory(*, api_key: str, timeout: float, max_retries: int) -> AsyncOpenAI:
        assert api_key == "test-only"
        assert max_retries == 0
        connection = httpx2.AsyncClient(transport=httpx2.MockTransport(transport))
        connections.append(connection)
        return AsyncOpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
            http_client=connection,
        )

    monkeypatch.setattr("app.main.create_db_and_tables", create_tables)
    monkeypatch.setattr("app.main.engine", engine)
    monkeypatch.setattr("app.clients.openai.AsyncOpenAI", sdk_factory)
    monkeypatch.setitem(app.dependency_overrides, get_db, test_db)
    async with lifespan(app):
        async with sessions() as session:
            session.add(
                User(id=1, username="delete_owner", password_hash="test", name="회원")
            )
            await session.commit()
        token, _ = create_access_token(1)
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield _DeleteApp(
                client, sessions, request_sessions, sdk_requests, database_url
            )
    assert len(connections) == 1
    assert connections[0].is_closed


async def _stored_chat(
    sessions: async_sessionmaker[AsyncSession], chat_id: UUID
) -> tuple[Chat, list[ChatLog]]:
    """별도 세션에서 삭제 상태와 보존된 대화 기록을 조회한다."""
    async with sessions() as session:
        chat = await session.get(Chat, chat_id)
        assert chat is not None
        messages = await session.scalars(
            select(ChatLog).where(ChatLog.chat_id == chat_id)
        )
        return chat, list(messages.all())


def _assert_error(response: Response, code: str, status: int = 404) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert UUID(response.headers["X-Request-ID"]).version == 4


async def _assert_hidden(client: AsyncClient, path: str) -> None:
    """삭제된 방은 조회와 새 질문에서 제외된다."""
    listing = await client.get("/api/v1/chats")
    assert listing.status_code == 200
    assert listing.json() == {"items": []}
    _assert_error(await client.get(path), "CHAT_NOT_FOUND")
    _assert_error(
        await client.post(path + "/messages", json={"question": "삭제 후 질문"}),
        "CHAT_NOT_FOUND",
    )


@pytest.mark.parametrize(
    ("scenario", "status", "error_code"),
    [
        ("success", 201, None),
        ("failure", 502, "AI_UNAVAILABLE"),
        ("timeout", 504, "AI_TIMEOUT"),
    ],
)
def test_delete_during_ai_preserves_response_and_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    status: int,
    error_code: str | None,
) -> None:
    """AI 대기 중 삭제가 완료되고 기존 요청의 성공·실패 결과가 보존된다."""

    async def run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def respond(request: httpx2.Request) -> httpx2.Response:
            started.set()
            await release.wait()
            if scenario == "timeout":
                raise httpx2.ReadTimeout("test-only timeout", request=request)
            if scenario == "failure":
                return httpx2.Response(500, json={"error": {"message": "test-only"}})
            return httpx2.Response(
                200,
                json={
                    "id": "resp_deleted",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": "test-model",
                    "output": [
                        {
                            "id": "msg_deleted",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "삭제 후 답변",
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                },
            )

        async with _delete_app(tmp_path, monkeypatch, respond) as env:
            created = await env.client.post("/api/v1/chats")
            assert created.status_code == 201
            chat_id = UUID(created.json()["chat_id"])
            path = f"/api/v1/chats/{chat_id}"
            previous_id = uuid4()
            async with env.sessions() as session:
                session.add(
                    ChatLog(
                        request_id=previous_id,
                        chat_id=chat_id,
                        question="이전 질문",
                        answer="이전 답변",
                        model="test-model",
                        status="completed",
                        finished_at=datetime.now(UTC),
                    )
                )
                await session.commit()
            previous = (await env.client.get(path)).json()["messages"][0]
            question_task = asyncio.create_task(
                env.client.post(path + "/messages", json={"question": "진행 중 질문"})
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                assert not env.request_sessions[-1].in_transaction()
                _, messages = await _stored_chat(env.sessions, chat_id)
                pending = next(m for m in messages if m.request_id != previous_id)
                assert pending.status == "pending"
                assert pending.answer is pending.error_code is None
                assert pending.finished_at is None
                deleted = await asyncio.wait_for(env.client.delete(path), timeout=5)
                assert deleted.status_code == 204 and deleted.content == b""
                assert not question_task.done()
                chat, messages = await _stored_chat(env.sessions, chat_id)
                deleted_at = chat.deleted_at
                assert deleted_at is not None and deleted_at.tzinfo == UTC
                still_pending = next(
                    m for m in messages if m.request_id == pending.request_id
                )
                assert still_pending.status == "pending"
                await _assert_hidden(env.client, path)
                assert len(env.sdk_requests) == 1
            finally:
                release.set()
                question_response = await asyncio.wait_for(question_task, timeout=5)
            assert question_response.status_code == status
            if error_code is None:
                assert question_response.json()["answer"] == "삭제 후 답변"
                assert question_response.json()["status"] == "completed"
            else:
                _assert_error(question_response, error_code, status)
            await _assert_hidden(env.client, path)
            _assert_error(await env.client.delete(path), "CHAT_NOT_FOUND")
            assert len(env.sdk_requests) == 1
            database_url = env.database_url

        reopened = create_async_engine(database_url)
        try:
            chat, messages = await _stored_chat(async_sessionmaker(reopened), chat_id)
            assert chat.deleted_at == deleted_at
            assert len(messages) == 2
            previous_stored = next(m for m in messages if m.request_id == previous_id)
            assert MessageResponse.model_validate(previous_stored).model_dump(
                mode="json"
            ) == previous
            result = next(m for m in messages if m.request_id == pending.request_id)
            assert str(result.request_id) == question_response.headers["X-Request-ID"]
            assert result.question == "진행 중 질문"
            assert result.model == "test-model"
            assert result.status == ("completed" if error_code is None else "failed")
            assert result.error_code == error_code
            assert result.answer == ("삭제 후 답변" if error_code is None else None)
            assert result.finished_at is not None and result.finished_at.tzinfo == UTC
            if error_code is None:
                assert MessageResponse.model_validate(result).model_dump(
                    mode="json"
                ) == question_response.json()
        finally:
            await reopened.dispose()

    asyncio.run(run())


def test_concurrent_delete_only_one_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """동시에 시작한 삭제 중 하나만 성공하고 최초 삭제 시각을 유지한다."""

    async def run() -> None:
        async def reject_ai(request: httpx2.Request) -> httpx2.Response:
            raise AssertionError("삭제는 AI를 호출하지 않아야 한다.")

        async with _delete_app(tmp_path, monkeypatch, reject_ai) as env:
            created = await env.client.post("/api/v1/chats")
            assert created.status_code == 201
            chat_id = UUID(created.json()["chat_id"])
            path = f"/api/v1/chats/{chat_id}"
            both_started = asyncio.Event()
            calls: list[tuple[datetime, bool]] = []
            original = ChatRepository.soft_delete

            async def concurrent_delete(
                repository: ChatRepository,
                chat_id: UUID,
                user_id: int,
                deleted_at: datetime,
            ) -> bool:
                index = len(calls)
                calls.append((deleted_at, False))
                if len(calls) == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), timeout=5)
                result = await original(repository, chat_id, user_id, deleted_at)
                calls[index] = (deleted_at, result)
                return result

            with monkeypatch.context() as patch:
                patch.setattr(ChatRepository, "soft_delete", concurrent_delete)
                responses = await asyncio.wait_for(
                    asyncio.gather(env.client.delete(path), env.client.delete(path)),
                    timeout=5,
                )
            assert sorted(response.status_code for response in responses) == [204, 404]
            assert len(calls) == 2
            assert sum(result for _, result in calls) == 1
            winner = next(timestamp for timestamp, result in calls if result)
            for response in responses:
                if response.status_code == 204:
                    assert response.content == b""
                else:
                    _assert_error(response, "CHAT_NOT_FOUND")
            assert responses[0].headers["X-Request-ID"] != responses[1].headers[
                "X-Request-ID"
            ]
            chat, messages = await _stored_chat(env.sessions, chat_id)
            assert chat.deleted_at == winner
            assert messages == []
            _assert_error(await env.client.delete(path), "CHAT_NOT_FOUND")
            await _assert_hidden(env.client, path)
            chat, _ = await _stored_chat(env.sessions, chat_id)
            assert chat.deleted_at == winner
            assert env.sdk_requests == []

    asyncio.run(run())
