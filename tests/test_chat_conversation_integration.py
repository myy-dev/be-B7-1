import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx2
import pytest
from httpx import ASGITransport, AsyncClient, Response
from openai import AsyncOpenAI
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.clients.ai import DEFAULT_INSTRUCTIONS
from app.core.config import Settings
from app.core.database import Base, _enable_sqlite_foreign_keys, get_db
from app.core.errors import DatabaseSaveError
from app.core.security import create_access_token
from app.main import app, lifespan
from app.models.chat import Chat, ChatLog
from app.models.user import User
from app.repositories.chat_repository import ChatRepository


@dataclass
class _ConversationApp:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    request_sessions: list[AsyncSession]
    sdk_requests: list[httpx2.Request]
    database_url: str


def _sdk_response(answer: str, status: str = "completed") -> dict[str, object]:
    return {
        "id": "resp_conversation_test",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "test-model",
        "output": [
            {
                "id": "msg_conversation_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": answer, "annotations": []}],
            }
        ],
    }


@asynccontextmanager
async def _conversation_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[
        [httpx2.Request], Awaitable[httpx2.Response | None]
    ] | None = None,
    timeout: float = 30,
) -> AsyncIterator[_ConversationApp]:
    """실제 앱·JWT·SDK를 임시 파일 DB와 모의 HTTP에 연결한다."""
    settings = Settings(
        _env_file=None,
        openai_api_key="test-only",
        openai_model="test-model",
        ai_timeout_seconds=timeout,
        ai_max_retries=0,
        jwt_secret_key="test-only-chat-conversation-secret-123456789",
    )
    monkeypatch.setattr("app.main.settings", settings)
    monkeypatch.setattr("app.core.security.get_settings", lambda: settings)
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'conversation.db'}"
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
        if respond is not None:
            response = await respond(request)
            if response is not None:
                return response
        if request.url.path == "/v1/conversations":
            return httpx2.Response(
                200,
                json={
                    "id": f"conv_{uuid4().hex}",
                    "object": "conversation",
                    "created_at": 1,
                    "metadata": {},
                },
            )
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        return httpx2.Response(
            200, json=_sdk_response(f"답변: {payload['input'][-1]['content']}")
        )

    def sdk_factory(*, api_key: str, timeout: float, max_retries: int) -> AsyncOpenAI:
        assert api_key == "test-only"
        assert max_retries == 0
        connection = httpx2.AsyncClient(transport=httpx2.MockTransport(transport))
        connections.append(connection)
        return AsyncOpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
            http_client=connection,
        )

    monkeypatch.setattr("app.main.create_db_and_tables", create_tables)
    monkeypatch.setattr("app.main.engine", engine)
    monkeypatch.setattr("app.clients.openai.AsyncOpenAI", sdk_factory)
    monkeypatch.setitem(app.dependency_overrides, get_db, test_db)
    async with lifespan(app):
        async with sessions() as session:
            for user_id in (1, 2):
                if await session.get(User, user_id) is None:
                    session.add(
                        User(
                            id=user_id,
                            username=f"conversation_owner_{user_id}",
                            password_hash="test",
                            name="회원",
                        )
                    )
            await session.commit()
        token, _ = create_access_token(1)
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield _ConversationApp(
                client, sessions, request_sessions, sdk_requests, database_url
            )
    assert len(connections) == 1
    assert connections[0].is_closed


async def _stored_chat(
    sessions: async_sessionmaker[AsyncSession], chat_id: UUID
) -> tuple[Chat, list[ChatLog]]:
    """별도 세션에서 채팅방의 문맥 ID와 저장된 기록을 조회한다."""
    async with sessions() as session:
        chat = await session.get(Chat, chat_id)
        assert chat is not None
        messages = await session.scalars(
            select(ChatLog).where(ChatLog.chat_id == chat_id)
        )
        return chat, list(messages.all())


def _payloads(env: _ConversationApp, endpoint: str) -> list[dict[str, object]]:
    return [
        json.loads(request.content)
        for request in env.sdk_requests
        if request.url.path == f"/v1/{endpoint}"
    ]


def _assert_error(response: Response, code: str, status: int) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "hidden" not in response.text


def test_conversation_created_once_reused_across_restart_and_separate_rooms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """문맥 ID를 첫 질문 전에 저장하고 방별·재시작 이후에도 재사용한다."""
    history = AsyncMock(side_effect=AssertionError("OpenAI는 DB 이력을 조회하지 않는다."))
    monkeypatch.setattr(ChatRepository, "list_recent_completed", history)

    async def run() -> None:
        verified_calls = 0

        async def verify_committed(request: httpx2.Request) -> httpx2.Response | None:
            nonlocal verified_calls
            if verified_calls == 2:
                return None
            verified_calls += 1
            assert not env.request_sessions[-1].in_transaction()
            current, pending = await _stored_chat(env.sessions, room)
            assert len(pending) == 1 and pending[0].status == "pending"
            if request.url.path == "/v1/conversations":
                assert current.conversation_id is None
            else:
                payload = json.loads(request.content)
                assert current.conversation_id == payload["conversation"]
            return None

        async with _conversation_app(tmp_path, monkeypatch, verify_committed) as env:
            created = await env.client.post("/api/v1/chats")
            assert created.status_code == 201
            assert "conversation_id" not in created.json()
            room = UUID(created.json()["chat_id"])
            path = f"/api/v1/chats/{room}/messages"
            untouched, records = await _stored_chat(env.sessions, room)
            assert untouched.conversation_id is None
            assert records == []

            # 호출 시점의 커밋 여부는 SDK 경계에서 별도 세션으로 확인한다.
            first = await env.client.post(path, json={"question": "첫 질문"})
            assert first.status_code == 201
            stored, records = await _stored_chat(env.sessions, room)
            conversation_id = stored.conversation_id
            assert conversation_id is not None
            assert records[0].status == "completed"
            assert len(env.sdk_requests) == 2
            assert verified_calls == 2

            second = await env.client.post(path, json={"question": "두 번째 질문"})
            assert second.status_code == 201
            other = (await env.client.post("/api/v1/chats")).json()["chat_id"]
            other_response = await env.client.post(
                f"/api/v1/chats/{other}/messages", json={"question": "다른 방 질문"}
            )
            assert other_response.status_code == 201
            other_chat, _ = await _stored_chat(env.sessions, UUID(other))
            assert other_chat.conversation_id != conversation_id
            assert len(_payloads(env, "conversations")) == 2
            payloads = _payloads(env, "responses")
            assert [payload["conversation"] for payload in payloads] == [
                conversation_id,
                conversation_id,
                other_chat.conversation_id,
            ]
            for payload, question in zip(
                payloads, ("첫 질문", "두 번째 질문", "다른 방 질문"), strict=True
            ):
                assert payload["input"] == [{"role": "user", "content": question}]
                assert payload["instructions"] == DEFAULT_INSTRUCTIONS
                assert payload["context_management"] == [
                    {"type": "compaction", "compact_threshold": 20_000}
                ]
                assert payload["store"] is True

        async with _conversation_app(tmp_path, monkeypatch) as restarted:
            resumed = await restarted.client.post(
                path, json={"question": "재시작 후 질문"}
            )
            assert resumed.status_code == 201
            assert _payloads(restarted, "conversations") == []
            assert (
                _payloads(restarted, "responses")[0]["conversation"]
                == conversation_id
            )
            stored, records = await _stored_chat(restarted.sessions, room)
            assert stored.conversation_id == conversation_id
            assert len(records) == 3

    asyncio.run(run())
    history.assert_not_awaited()


def test_existing_room_records_are_preserved_without_uploading_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기존 방은 새 문맥을 생성하고 기존 DB 기록은 조회용으로 보존한다."""
    history = AsyncMock(side_effect=AssertionError("기존 이력은 자동 이관하지 않는다."))
    monkeypatch.setattr(ChatRepository, "list_recent_completed", history)

    async def run() -> None:
        async with _conversation_app(tmp_path, monkeypatch) as env:
            created = await env.client.post("/api/v1/chats")
            room = UUID(created.json()["chat_id"])
            old_id = uuid4()
            async with env.sessions() as session:
                session.add(
                    ChatLog(
                        request_id=old_id,
                        chat_id=room,
                        question="이전 DB 질문",
                        answer="이전 DB 답변",
                        model="test-model",
                        status="completed",
                        finished_at=datetime.now(UTC),
                    )
                )
                await session.commit()
            result = await env.client.post(
                f"/api/v1/chats/{room}/messages", json={"question": "새 문맥 질문"}
            )
            assert result.status_code == 201
            assert len(_payloads(env, "conversations")) == 1
            assert _payloads(env, "conversations")[0].get("items", []) == []
            assert _payloads(env, "responses")[0]["input"] == [
                {"role": "user", "content": "새 문맥 질문"}
            ]
            stored, records = await _stored_chat(env.sessions, room)
            assert stored.conversation_id is not None
            old = next(record for record in records if record.request_id == old_id)
            assert (old.question, old.answer, old.status) == (
                "이전 DB 질문", "이전 DB 답변", "completed"
            )
            detail = await env.client.get(f"/api/v1/chats/{room}")
            assert detail.status_code == 200
            assert len(detail.json()["messages"]) == 2

    asyncio.run(run())
    history.assert_not_awaited()


@pytest.mark.parametrize("failure", ["server", "timeout"])
def test_creation_failure_is_saved_and_next_request_can_create_conversation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """문맥 생성 실패는 failed로 기록하고 다음 요청의 생성을 허용한다."""

    async def run() -> None:
        failed = False

        async def respond(request: httpx2.Request) -> httpx2.Response | None:
            nonlocal failed
            if request.url.path == "/v1/conversations" and not failed:
                failed = True
                if failure == "timeout":
                    raise httpx2.ReadTimeout("hidden create timeout", request=request)
                return httpx2.Response(
                    500, json={"error": {"message": "hidden creation error"}}
                )
            return None

        async with _conversation_app(tmp_path, monkeypatch, respond) as env:
            room = UUID((await env.client.post("/api/v1/chats")).json()["chat_id"])
            path = f"/api/v1/chats/{room}/messages"
            first = await env.client.post(path, json={"question": "생성 실패 질문"})
            code = "AI_TIMEOUT" if failure == "timeout" else "AI_UNAVAILABLE"
            _assert_error(first, code, 504 if failure == "timeout" else 502)
            stored, records = await _stored_chat(env.sessions, room)
            assert stored.conversation_id is None
            assert len(records) == 1
            assert records[0].status == "failed"
            assert records[0].error_code == code
            assert records[0].finished_at is not None
            assert _payloads(env, "responses") == []
            second = await env.client.post(path, json={"question": "재질문"})
            assert second.status_code == 201
            assert len(_payloads(env, "conversations")) == 2
            assert len(_payloads(env, "responses")) == 1

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["server", "timeout", "incomplete"])
def test_answer_failure_keeps_saved_conversation_for_next_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """답변 실패 후에도 이미 저장한 문맥 ID로 다음 질문을 전송한다."""

    async def run() -> None:
        failed = False

        async def respond(request: httpx2.Request) -> httpx2.Response | None:
            nonlocal failed
            if request.url.path == "/v1/responses" and not failed:
                failed = True
                if failure == "timeout":
                    raise httpx2.ReadTimeout("hidden response timeout", request=request)
                if failure == "incomplete":
                    return httpx2.Response(
                        200, json=_sdk_response("부분 답변", "incomplete")
                    )
                return httpx2.Response(
                    500, json={"error": {"message": "hidden response error"}}
                )
            return None

        async with _conversation_app(tmp_path, monkeypatch, respond) as env:
            room = UUID((await env.client.post("/api/v1/chats")).json()["chat_id"])
            path = f"/api/v1/chats/{room}/messages"
            first = await env.client.post(path, json={"question": "답변 실패 질문"})
            code = "AI_TIMEOUT" if failure == "timeout" else "AI_UNAVAILABLE"
            _assert_error(first, code, 504 if failure == "timeout" else 502)
            stored, records = await _stored_chat(env.sessions, room)
            saved_id = stored.conversation_id
            assert saved_id is not None
            assert len(records) == 1 and records[0].status == "failed"
            assert records[0].error_code == code
            second = await env.client.post(path, json={"question": "다음 질문"})
            assert second.status_code == 201
            assert len(_payloads(env, "conversations")) == 1
            assert [p["conversation"] for p in _payloads(env, "responses")] == [
                saved_id, saved_id
            ]
            stored, records = await _stored_chat(env.sessions, room)
            assert stored.conversation_id == saved_id
            assert sorted(record.status for record in records) == [
                "completed", "failed"
            ]

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["lookup", "save"])
def test_conversation_database_error_stops_inference_and_keeps_db_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    phase: str,
) -> None:
    """문맥 조회·저장 DB 실패를 AI 오류로 바꾸지 않고 답변 요청을 중단한다."""
    logger = logging.getLogger("app.events")
    monkeypatch.setattr(logger, "handlers", [caplog.handler])
    monkeypatch.setattr(logger, "propagate", False)
    caplog.set_level(logging.INFO, logger="app.events")
    error = OperationalError("hidden statement", {}, RuntimeError("hidden database"))
    method = "get_conversation_id" if phase == "lookup" else "save_conversation_id"
    failure = error if phase == "lookup" else DatabaseSaveError(error)
    monkeypatch.setattr(ChatRepository, method, AsyncMock(side_effect=failure))

    async def run() -> None:
        async with _conversation_app(tmp_path, monkeypatch) as env:
            room = UUID((await env.client.post("/api/v1/chats")).json()["chat_id"])
            response = await env.client.post(
                f"/api/v1/chats/{room}/messages", json={"question": "DB 실패 질문"}
            )
            _assert_error(response, "DB_ERROR", 500)
            stored, records = await _stored_chat(env.sessions, room)
            assert stored.conversation_id is None
            assert _payloads(env, "responses") == []
            assert len(_payloads(env, "conversations")) == (1 if phase == "save" else 0)
            assert len(records) == (1 if phase == "save" else 0)
            if phase == "save":
                assert records[0].status == "pending"
                assert records[0].error_code is records[0].finished_at is None
            events = [
                record.getMessage()
                for record in caplog.records
                if (
                    getattr(record, "request_id", None)
                    == response.headers["X-Request-ID"]
                )
            ]
            assert "ai_call_failed" not in events
            assert ("db_save_failed" in events) == (phase == "save")
            assert "api_error" in events or phase == "save"

    asyncio.run(run())


def test_first_request_timeout_includes_conversation_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """문맥 생성 시간을 포함한 전체 제한 시간과 실패 후 ID 재사용을 확인한다."""

    async def run() -> None:
        cancelled = False

        async def respond(request: httpx2.Request) -> httpx2.Response | None:
            nonlocal cancelled
            if request.url.path == "/v1/conversations":
                await asyncio.sleep(0.12)
            elif json.loads(request.content)["input"][-1]["content"] == "시간 제한 질문":
                try:
                    await asyncio.sleep(0.15)
                except asyncio.CancelledError:
                    cancelled = True
                    raise
            return None

        async with (
            _conversation_app(tmp_path, monkeypatch, respond, timeout=0.2) as env
        ):
            room = UUID((await env.client.post("/api/v1/chats")).json()["chat_id"])
            path = f"/api/v1/chats/{room}/messages"
            first = await env.client.post(path, json={"question": "시간 제한 질문"})
            _assert_error(first, "AI_TIMEOUT", 504)
            assert cancelled
            stored, records = await _stored_chat(env.sessions, room)
            assert stored.conversation_id is not None
            assert records[0].status == "failed"
            assert records[0].error_code == "AI_TIMEOUT"
            second = await env.client.post(path, json={"question": "빠른 질문"})
            assert second.status_code == 201
            assert len(_payloads(env, "conversations")) == 1

    asyncio.run(run())


def test_user_gate_and_deletion_during_conversation_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """문맥 생성 중 중복 질문을 거절하고 삭제된 방의 시작된 요청은 완료한다."""

    async def run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        blocked = False

        async def respond(request: httpx2.Request) -> httpx2.Response | None:
            nonlocal blocked
            if request.url.path == "/v1/conversations" and not blocked:
                blocked = True
                started.set()
                await release.wait()
            return None

        async with _conversation_app(tmp_path, monkeypatch, respond) as env:
            room = UUID((await env.client.post("/api/v1/chats")).json()["chat_id"])
            another = (await env.client.post("/api/v1/chats")).json()["chat_id"]
            path = f"/api/v1/chats/{room}"
            task = asyncio.create_task(
                env.client.post(path + "/messages", json={"question": "생성 중 질문"})
            )
            try:
                await asyncio.wait_for(started.wait(), 2)
                duplicate = await env.client.post(
                    f"/api/v1/chats/{another}/messages", json={"question": "중복 질문"}
                )
                _assert_error(duplicate, "CHAT_BUSY", 409)
                untouched, rows = await _stored_chat(env.sessions, UUID(another))
                assert untouched.conversation_id is None and rows == []
                assert len(_payloads(env, "conversations")) == 1
                token, _ = create_access_token(2)
                headers = {"Authorization": f"Bearer {token}"}
                other_room = (
                    await env.client.post("/api/v1/chats", headers=headers)
                ).json()["chat_id"]
                other = await env.client.post(
                    f"/api/v1/chats/{other_room}/messages",
                    headers=headers,
                    json={"question": "다른 사용자 질문"},
                )
                assert other.status_code == 201
                deleted = await env.client.delete(path)
                assert deleted.status_code == 204
            finally:
                release.set()
                first = await task
            assert first.status_code == 201
            stored, records = await _stored_chat(env.sessions, room)
            assert stored.deleted_at is not None
            assert stored.conversation_id is not None
            assert len(records) == 1 and records[0].status == "completed"
            _assert_error(await env.client.get(path), "CHAT_NOT_FOUND", 404)
            next_response = await env.client.post(
                f"/api/v1/chats/{another}/messages", json={"question": "점유 해제 후 질문"}
            )
            assert next_response.status_code == 201
            assert len(_payloads(env, "conversations")) == 3

    asyncio.run(run())


def test_conversation_id_commit_failure_rolls_back_and_session_can_be_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실제 ID 갱신의 커밋 실패를 롤백하고 같은 세션에서 다시 저장한다."""

    async def run() -> None:
        async with _conversation_app(tmp_path, monkeypatch) as env:
            room = UUID((await env.client.post("/api/v1/chats")).json()["chat_id"])
            async with env.sessions() as session:
                repository = ChatRepository(session)
                commit = session.commit
                rollback = AsyncMock(wraps=session.rollback)
                error = OperationalError(
                    "hidden commit", {}, RuntimeError("hidden commit failure")
                )
                monkeypatch.setattr(session, "commit", AsyncMock(side_effect=error))
                monkeypatch.setattr(session, "rollback", rollback)
                with pytest.raises(DatabaseSaveError) as failure:
                    await repository.save_conversation_id(room, "conv_rolled_back")
                assert failure.value.original is error
                rollback.assert_awaited_once()
                assert not session.in_transaction()
                stored, _ = await _stored_chat(env.sessions, room)
                assert stored.conversation_id is None

                monkeypatch.setattr(session, "commit", commit)
                await repository.save_conversation_id(room, "conv_recovered")
                assert await repository.get_conversation_id(room) == "conv_recovered"
                stored, _ = await _stored_chat(env.sessions, room)
                assert stored.conversation_id == "conv_recovered"
                assert _payloads(env, "conversations") == []

    asyncio.run(run())


def test_conversation_lookup_is_fresh_and_id_save_preserves_deleted_room_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """다른 세션의 ID 변경을 읽고 삭제된 방에도 기록을 보존하며 저장한다."""

    async def run() -> None:
        async with _conversation_app(tmp_path, monkeypatch) as env:
            room = UUID((await env.client.post("/api/v1/chats")).json()["chat_id"])
            old_id = uuid4()
            deleted_at = datetime.now(UTC)
            async with env.sessions() as session:
                stale = await session.get(Chat, room)
                assert stale is not None and stale.conversation_id is None
                repository = ChatRepository(session)
                async with env.sessions() as other_session:
                    other_repository = ChatRepository(other_session)
                    await other_repository.save_message(
                        ChatLog(
                            request_id=old_id,
                            chat_id=room,
                            question="보존할 질문",
                            answer="보존할 답변",
                            model="test-model",
                            status="completed",
                            finished_at=datetime.now(UTC),
                        )
                    )
                    await other_repository.save_conversation_id(room, "conv_external")
                    assert await other_repository.soft_delete(room, 1, deleted_at)
                assert stale.conversation_id is None
                assert await repository.get_conversation_id(room) == "conv_external"
                await repository.save_conversation_id(room, "conv_after_delete")

            stored, records = await _stored_chat(env.sessions, room)
            assert stored.conversation_id == "conv_after_delete"
            assert stored.deleted_at == deleted_at
            assert len(records) == 1
            assert records[0].request_id == old_id
            assert (records[0].question, records[0].answer, records[0].status) == (
                "보존할 질문", "보존할 답변", "completed"
            )
            _assert_error(
                await env.client.get(f"/api/v1/chats/{room}"), "CHAT_NOT_FOUND", 404
            )

    asyncio.run(run())
