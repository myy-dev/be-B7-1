"""격리한 SQLite에서 채팅 API의 저장·조회·소유권을 검증한다."""

import asyncio
import subprocess
import sys
from collections.abc import AsyncGenerator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_ai_client, get_current_user_id
from app.api.v1.router import router
from app.clients.ai import AIClient
from app.core.database import Base, _enable_sqlite_foreign_keys, get_db
from app.core.errors import APIError, configure_request_processing
from app.models.chat import Chat, ChatLog
from app.repositories.chat import ChatRepository
from app.schemas.error import ErrorCode


@dataclass
class _ChatAPI:
    app: FastAPI
    client: TestClient
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    user_id: int = 2**40 + 7

    def authenticate(self) -> None:
        self.app.dependency_overrides[get_current_user_id] = lambda: self.user_id

    def seed(self, *rows: Chat | ChatLog) -> None:
        async def save() -> None:
            async with self.sessions() as session:
                session.add_all(rows)
                await session.commit()

        asyncio.run(save())

    def stored_chats(self) -> list[Chat]:
        async def read() -> list[Chat]:
            async with self.sessions() as session:
                return list((await session.scalars(select(Chat))).all())

        return asyncio.run(read())

    def drop_tables(self) -> None:
        async def drop() -> None:
            async with self.engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)

        asyncio.run(drop())


@pytest.fixture
def chat_api() -> Iterator[_ChatAPI]:
    """운영 DB·인증·설정을 사용하지 않는 테스트 앱과 저장소를 제공한다.

    Yields:
        요청마다 새 세션을 사용하는 채팅 API 테스트 환경.
    """
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def create_tables() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_tables())
    app = FastAPI()
    configure_request_processing(app)
    app.include_router(router)

    async def test_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    client = TestClient(app)
    try:
        yield _ChatAPI(app, client, engine, sessions)
    finally:
        app.dependency_overrides.clear()
        client.close()
        asyncio.run(engine.dispose())


def _assert_error(response: Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    error = response.json()["error"]
    assert set(error) == {"code", "message", "request_id"}
    assert error["code"] == code
    assert UUID(error["request_id"]).version == 4
    assert response.headers["X-Request-ID"] == error["request_id"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/chats"),
        ("GET", "/api/v1/chats"),
        ("GET", "/api/v1/chats/00000000-0000-4000-8000-000000000001"),
    ],
)
def test_unconnected_auth_rejects_spoofed_identity(
    chat_api: _ChatAPI, method: str, path: str
) -> None:
    """임의의 인증 정보나 사용자 ID를 보내도 인증 연결 전에는 거절한다."""
    response = chat_api.client.request(
        method,
        path,
        headers={
            "Authorization": "Bearer forged-token",
            "Cookie": "session=forged-session",
            "X-User-ID": str(chat_api.user_id),
        },
        params={"user_id": chat_api.user_id},
        json={"user_id": chat_api.user_id},
    )
    _assert_error(response, 401, "UNAUTHORIZED")
    assert chat_api.stored_chats() == []


def test_create_persists_authenticated_owner(chat_api: _ChatAPI) -> None:
    """채팅방은 인증된 사용자에게 저장되고 공개 필드만 반환한다."""
    chat_api.authenticate()
    response = chat_api.client.post(
        "/api/v1/chats", json={"user_id": chat_api.user_id + 1}
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"chat_id", "created_at"}
    assert UUID(body["chat_id"])
    assert datetime.fromisoformat(body["created_at"]).utcoffset() == timedelta(0)
    chats = chat_api.stored_chats()
    assert len(chats) == 1
    assert chats[0].chat_id == UUID(body["chat_id"])
    assert chats[0].user_id == chat_api.user_id
    assert chats[0].created_at == datetime.fromisoformat(body["created_at"])
    assert chat_api.client.get("/api/v1/chats").json() == {"items": [body]}


def test_empty_list_has_no_pagination_fields(chat_api: _ChatAPI) -> None:
    """채팅방이 없으면 명세의 빈 목록을 반환한다."""
    chat_api.authenticate()
    response = chat_api.client.get("/api/v1/chats")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_list_filters_owner_and_orders_time_then_uuid(chat_api: _ChatAPI) -> None:
    """본인 목록을 시각·UUID 내림차순으로 반환한다."""
    chat_api.authenticate()
    created_at = datetime(2026, 10, 5, 1, tzinfo=UTC)
    chat_ids = [
        UUID(f"00000000-0000-4000-8000-{number:012x}") for number in range(1, 5)
    ]
    chat_api.seed(
        Chat(chat_id=chat_ids[0], user_id=chat_api.user_id, created_at=created_at),
        Chat(chat_id=chat_ids[1], user_id=chat_api.user_id, created_at=created_at),
        Chat(
            chat_id=chat_ids[2],
            user_id=chat_api.user_id,
            created_at=created_at + timedelta(seconds=1),
        ),
        Chat(
            chat_id=chat_ids[3],
            user_id=chat_api.user_id + 1,
            created_at=created_at + timedelta(seconds=2),
        ),
    )
    response = chat_api.client.get("/api/v1/chats")
    assert response.status_code == 200
    assert set(response.json()) == {"items"}
    items = response.json()["items"]
    assert [item["chat_id"] for item in items] == [
        str(chat_ids[2]),
        str(chat_ids[1]),
        str(chat_ids[0]),
    ]
    assert all(set(item) == {"chat_id", "created_at"} for item in items)


def test_detail_for_empty_chat_returns_empty_messages(chat_api: _ChatAPI) -> None:
    """본인 채팅방에 대화가 없으면 빈 배열과 UTC 시각을 반환한다."""
    chat_api.authenticate()
    chat_id = UUID("00000000-0000-4000-8000-000000000001")
    chat_api.seed(
        Chat(
            chat_id=chat_id,
            user_id=chat_api.user_id,
            created_at=datetime(2026, 10, 5, 10, tzinfo=timezone(timedelta(hours=9))),
        )
    )
    response = chat_api.client.get(f"/api/v1/chats/{chat_id}")
    assert response.status_code == 200
    assert response.json() == {
        "chat_id": str(chat_id),
        "created_at": "2026-10-05T01:00:00Z",
        "messages": [],
    }


def test_detail_includes_all_statuses_in_order(chat_api: _ChatAPI) -> None:
    """모든 처리 상태를 시각·요청 ID순으로 조회하고 다른 채팅을 제외한다."""
    chat_api.authenticate()
    chat_id = UUID("00000000-0000-4000-8000-000000000001")
    other_chat_id = UUID("00000000-0000-4000-8000-000000000002")
    created_at = datetime(2026, 10, 5, 10, tzinfo=timezone(timedelta(hours=9)))
    request_ids = [
        UUID(f"00000000-0000-4000-8000-{number:012x}") for number in range(1, 5)
    ]
    chat_api.seed(
        Chat(chat_id=chat_id, user_id=chat_api.user_id, created_at=created_at),
        Chat(chat_id=other_chat_id, user_id=chat_api.user_id, created_at=created_at),
    )
    chat_api.seed(
        ChatLog(
            request_id=request_ids[2],
            chat_id=chat_id,
            question="처리 중 질문",
            answer=None,
            status="pending",
            error_code=None,
            model="test-model",
            created_at=created_at + timedelta(seconds=2),
            finished_at=None,
        ),
        ChatLog(
            request_id=request_ids[1],
            chat_id=chat_id,
            question="실패한 질문",
            answer=None,
            status="failed",
            error_code="AI_TIMEOUT",
            model="test-model",
            created_at=created_at + timedelta(seconds=1),
            finished_at=created_at + timedelta(seconds=3),
        ),
        ChatLog(
            request_id=request_ids[0],
            chat_id=chat_id,
            question="성공한 질문",
            answer="완료 답변",
            status="completed",
            error_code=None,
            model="test-model",
            created_at=created_at + timedelta(seconds=1),
            finished_at=created_at + timedelta(seconds=2),
        ),
        ChatLog(
            request_id=request_ids[3],
            chat_id=other_chat_id,
            question="다른 채팅방 질문",
            answer=None,
            status="pending",
            error_code=None,
            model="test-model",
            created_at=created_at,
            finished_at=None,
        ),
    )
    response = chat_api.client.get(f"/api/v1/chats/{chat_id}")
    assert response.status_code == 200
    assert set(response.json()) == {"chat_id", "created_at", "messages"}
    messages = response.json()["messages"]
    assert [message["request_id"] for message in messages] == [
        str(request_id) for request_id in request_ids[:3]
    ]
    assert [message["status"] for message in messages] == [
        "completed",
        "failed",
        "pending",
    ]
    expected_fields = {
        "request_id",
        "chat_id",
        "question",
        "answer",
        "status",
        "error_code",
        "created_at",
        "finished_at",
    }
    assert all(set(message) == expected_fields for message in messages)
    assert all(message["chat_id"] == str(chat_id) for message in messages)
    assert messages[0]["answer"] == "완료 답변"
    assert messages[0]["error_code"] is None
    assert messages[0]["created_at"] == "2026-10-05T01:00:01Z"
    assert messages[0]["finished_at"] == "2026-10-05T01:00:02Z"
    assert messages[1]["answer"] is None
    assert messages[1]["error_code"] == "AI_TIMEOUT"
    assert messages[1]["finished_at"] == "2026-10-05T01:00:03Z"
    assert messages[2]["answer"] is None
    assert messages[2]["error_code"] is None
    assert messages[2]["finished_at"] is None
    repeated = chat_api.client.get(f"/api/v1/chats/{chat_id}")
    assert repeated.json()["messages"] == messages
    assert repeated.headers["X-Request-ID"] != response.headers["X-Request-ID"]


@pytest.mark.parametrize("owned_by_other", [False, True])
def test_missing_and_unowned_chats_share_404(
    chat_api: _ChatAPI, owned_by_other: bool
) -> None:
    """없는 채팅방과 타인 채팅방을 같은 404 응답으로 처리한다."""
    chat_api.authenticate()
    chat_id = UUID("00000000-0000-4000-8000-000000000001")
    if owned_by_other:
        chat_api.seed(
            Chat(
                chat_id=chat_id,
                user_id=chat_api.user_id + 1,
                created_at=datetime(2026, 10, 5, tzinfo=UTC),
            )
        )
    response = chat_api.client.get(f"/api/v1/chats/{chat_id}")
    _assert_error(response, 404, "CHAT_NOT_FOUND")


def test_invalid_chat_uuid_returns_input_error(chat_api: _ChatAPI) -> None:
    """잘못된 UUID 경로는 공통 입력 오류로 반환한다."""
    chat_api.authenticate()
    response = chat_api.client.get("/api/v1/chats/not-a-uuid")
    _assert_error(response, 422, "INVALID_INPUT")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/chats"),
        ("GET", "/api/v1/chats"),
        ("GET", "/api/v1/chats/00000000-0000-4000-8000-000000000001"),
    ],
)
def test_sql_failure_returns_database_error(
    chat_api: _ChatAPI, method: str, path: str
) -> None:
    """실제 조회·저장 SQL 실패를 공통 DB 오류로 변환한다."""
    chat_api.authenticate()
    chat_api.drop_tables()
    response = chat_api.client.request(method, path)
    _assert_error(response, 500, "DB_ERROR")
    assert "no such table" not in response.text
    assert "SELECT" not in response.text
    assert "INSERT" not in response.text


def test_create_failure_rolls_back_session(chat_api: _ChatAPI) -> None:
    """실제 저장 제약 오류 뒤 같은 세션으로 정상 채팅방을 저장한다."""

    async def create_after_failure() -> UUID:
        async with chat_api.sessions() as session:
            repository = ChatRepository(session)
            with pytest.raises(IntegrityError):
                await repository.create(None)  # type: ignore[arg-type]
            chat = await repository.create(chat_api.user_id)
            return chat.chat_id

    chat_id = asyncio.run(create_after_failure())
    chats = chat_api.stored_chats()
    assert len(chats) == 1
    assert chats[0].chat_id == chat_id
    assert chats[0].user_id == chat_api.user_id


def test_fresh_startup_registers_models_and_enforces_foreign_keys() -> None:
    """새 프로세스의 앱 DB 시작 처리가 모델 등록과 외래키 설정을 수행한다."""
    script = """
import asyncio
from unittest.mock import patch

import sqlalchemy.ext.asyncio as sa_async
from sqlalchemy import inspect, text

test_engine = sa_async.create_async_engine("sqlite+aiosqlite://")
with patch.object(sa_async, "create_async_engine", return_value=test_engine):
    from app.core.database import Base, engine

assert engine is test_engine
assert not Base.metadata.tables
from app.main import app, lifespan

async def verify_startup():
    async with lifespan(app):
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
            assert set(tables) == {"chats", "chat_logs"}
            assert await connection.scalar(text("PRAGMA foreign_keys")) == 1

asyncio.run(verify_startup())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _mock_ai(chat_api: _ChatAPI) -> MagicMock:
    ai = MagicMock(spec=AIClient)
    ai.model = "test-model"
    ai.generate_answer = AsyncMock(return_value="AI 답변")
    chat_api.app.dependency_overrides[get_ai_client] = lambda: ai
    return ai


def _messages(chat_api: _ChatAPI) -> list[ChatLog]:
    async def read() -> list[ChatLog]:
        async with chat_api.sessions() as session:
            return list((await session.scalars(select(ChatLog))).all())

    return asyncio.run(read())


def test_question_answer_is_committed_and_reused_as_context(
    chat_api: _ChatAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """질문이 AI 호출 전에 저장되고 답변은 다음 질문의 문맥으로 전달된다."""
    chat_api.authenticate()
    ai = _mock_ai(chat_api)
    chat_id = chat_api.client.post("/api/v1/chats").json()["chat_id"]
    original = ChatRepository.save_message
    sessions: list[AsyncSession] = []

    async def save(repository: ChatRepository, message: ChatLog) -> ChatLog:
        sessions.append(repository.session)
        return await original(repository, message)

    monkeypatch.setattr(ChatRepository, "save_message", save)

    async def answer(question: str, history: list[tuple[str, str]]) -> str:
        assert not sessions[-1].in_transaction()
        async with chat_api.sessions() as session:
            pending = list((await session.scalars(
                select(ChatLog).where(ChatLog.status == "pending")
            )).all())
            assert len(pending) == 1
            assert pending[0].question == question
            assert pending[0].answer is pending[0].finished_at is None
        return "AI 답변"

    ai.generate_answer.side_effect = answer
    first = chat_api.client.post(
        f"/api/v1/chats/{chat_id}/messages", json={"question": "  첫 질문  "}
    )
    assert first.status_code == 201
    body = first.json()
    assert body["question"] == "첫 질문"
    assert body["answer"] == "AI 답변"
    assert body["status"] == "completed"
    assert body["error_code"] is None
    assert body["finished_at"] is not None
    assert body["request_id"] == first.headers["X-Request-ID"]
    assert chat_api.client.get(f"/api/v1/chats/{chat_id}").json()["messages"] == [body]
    second = chat_api.client.post(
        f"/api/v1/chats/{chat_id}/messages", json={"question": "다음 질문"}
    )
    assert second.status_code == 201
    ai.generate_answer.assert_awaited_with("다음 질문", [("첫 질문", "AI 답변")])
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    assert len(_messages(chat_api)) == 2


@pytest.mark.parametrize("question", ["", "  ", None, 123])
def test_invalid_question_does_not_save_or_call_ai(
    chat_api: _ChatAPI, question: object
) -> None:
    """빈 질문·잘못된 타입은 저장하거나 AI에 전달하지 않는다."""
    chat_api.authenticate()
    ai = _mock_ai(chat_api)
    chat_id = chat_api.client.post("/api/v1/chats").json()["chat_id"]
    response = chat_api.client.post(
        f"/api/v1/chats/{chat_id}/messages", json={"question": question}
    )
    _assert_error(response, 422, "INVALID_INPUT")
    ai.generate_answer.assert_not_awaited()
    assert _messages(chat_api) == []


@pytest.mark.parametrize("other_owner", [False, True])
def test_unowned_question_does_not_save_or_call_ai(
    chat_api: _ChatAPI, other_owner: bool
) -> None:
    """타인 채팅방과 없는 채팅방에는 질문 기록을 만들지 않는다."""
    chat_api.authenticate()
    ai = _mock_ai(chat_api)
    chat_id = UUID("00000000-0000-4000-8000-000000000001")
    if other_owner:
        chat_api.seed(Chat(chat_id=chat_id, user_id=chat_api.user_id + 1))
    response = chat_api.client.post(
        f"/api/v1/chats/{chat_id}/messages", json={"question": "질문"}
    )
    _assert_error(response, 404, "CHAT_NOT_FOUND")
    ai.generate_answer.assert_not_awaited()
    assert _messages(chat_api) == []


def test_question_requires_auth_before_ai_settings(chat_api: _ChatAPI) -> None:
    """질문 전송도 실제 인증 연결 전에는 AI 설정 조회 없이 거절한다."""
    response = chat_api.client.post(
        "/api/v1/chats/00000000-0000-4000-8000-000000000001/messages",
        json={"question": "질문"},
    )
    _assert_error(response, 401, "UNAUTHORIZED")


@pytest.mark.parametrize(
    ("code", "status_code"),
    [("AI_TIMEOUT", 504), ("AI_UNAVAILABLE", 502), ("AI_CONFIGURATION_ERROR", 503)],
)
def test_ai_failure_preserves_failed_question(
    chat_api: _ChatAPI, code: ErrorCode, status_code: int
) -> None:
    """AI 실패 뒤 질문을 유지하고 같은 요청 ID에 실패 결과를 저장한다."""
    chat_api.authenticate()
    ai = _mock_ai(chat_api)
    ai.generate_answer.side_effect = APIError(code)
    chat_id = chat_api.client.post("/api/v1/chats").json()["chat_id"]
    response = chat_api.client.post(
        f"/api/v1/chats/{chat_id}/messages", json={"question": "질문"}
    )
    _assert_error(response, status_code, code)
    message = chat_api.client.get(f"/api/v1/chats/{chat_id}").json()["messages"][0]
    assert message["request_id"] == response.headers["X-Request-ID"]
    assert message["question"] == "질문"
    assert message["status"] == "failed"
    assert message["error_code"] == code
    assert message["answer"] is None
    assert message["finished_at"] is not None


def test_context_contains_only_last_five_completed_pairs(chat_api: _ChatAPI) -> None:
    """문맥은 해당 채팅방의 최근 성공 기록 5개만 시간순으로 포함한다."""
    chat_api.authenticate()
    ai = _mock_ai(chat_api)
    chat_id = UUID(chat_api.client.post("/api/v1/chats").json()["chat_id"])
    other = UUID(chat_api.client.post("/api/v1/chats").json()["chat_id"])
    moment = datetime(2026, 10, 5, tzinfo=UTC)
    rows = [
        ChatLog(
            request_id=UUID(f"00000000-0000-4000-8000-{number:012x}"),
            chat_id=chat_id, question=f"질문{number}", answer=f"답변{number}",
            status="completed", model="test-model",
            created_at=moment + timedelta(seconds=number), finished_at=moment,
        )
        for number in range(1, 8)
    ]
    rows.extend([
        ChatLog(
            request_id=UUID("00000000-0000-4000-8000-000000000008"),
            chat_id=chat_id, question="실패 질문", status="failed", model="test-model",
            error_code="AI_TIMEOUT", created_at=moment + timedelta(seconds=8),
            finished_at=moment,
        ),
        ChatLog(
            request_id=UUID("00000000-0000-4000-8000-000000000009"),
            chat_id=chat_id, question="진행 중", status="pending", model="test-model",
            created_at=moment + timedelta(seconds=9),
        ),
        ChatLog(
            request_id=UUID("00000000-0000-4000-8000-00000000000a"),
            chat_id=other, question="다른 방", answer="다른 답변",
            status="completed", model="test-model", created_at=moment,
            finished_at=moment,
        ),
    ])
    chat_api.seed(*rows)
    response = chat_api.client.post(
        f"/api/v1/chats/{chat_id}/messages", json={"question": "현재 질문"}
    )
    assert response.status_code == 201
    ai.generate_answer.assert_awaited_once_with(
        "현재 질문", [(f"질문{n}", f"답변{n}") for n in range(3, 8)]
    )


@pytest.mark.parametrize(
    ("failure_at", "ai_failure"), [(1, False), (2, False), (2, True)]
)
def test_question_or_answer_save_failure_never_returns_success(
    chat_api: _ChatAPI, monkeypatch: pytest.MonkeyPatch,
    failure_at: int, ai_failure: bool,
) -> None:
    """질문 저장 실패는 AI 호출을 막고 답변 저장 실패는 성공을 반환하지 않는다."""
    chat_api.authenticate()
    ai = _mock_ai(chat_api)
    if ai_failure:
        ai.generate_answer.side_effect = APIError("AI_UNAVAILABLE")
    chat_id = chat_api.client.post("/api/v1/chats").json()["chat_id"]
    original = ChatRepository.save_message
    calls = 0

    async def fail_save(repository: ChatRepository, message: ChatLog) -> ChatLog:
        nonlocal calls
        calls += 1
        if calls == failure_at:
            raise OperationalError("hidden sql", {}, Exception("hidden error"))
        return await original(repository, message)

    monkeypatch.setattr(ChatRepository, "save_message", fail_save)
    response = chat_api.client.post(
        f"/api/v1/chats/{chat_id}/messages", json={"question": "질문"}
    )
    _assert_error(response, 500, "DB_ERROR")
    assert ai.generate_answer.await_count == failure_at - 1
    saved = _messages(chat_api)
    if failure_at == 1:
        assert saved == []
    else:
        assert len(saved) == 1
        assert saved[0].status == "pending"
        assert saved[0].answer is None
