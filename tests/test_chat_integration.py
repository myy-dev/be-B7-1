import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx2
import pytest
from httpx import ASGITransport, AsyncClient, Response
from openai import AsyncOpenAI
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_current_user_id
from app.core.config import Settings
from app.core.database import Base, _enable_sqlite_foreign_keys, get_db
from app.core.errors import APIError
from app.core.logging import EventLogFormatter
from app.main import app, lifespan
from app.models.chat import Chat, ChatLog
from app.models.user import User
from app.schemas.chat import MessageResponse
from app.schemas.error import ErrorCode


def _sdk_response(status: str, answer: str) -> dict[str, object]:
    return {
        "id": "resp_integration",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "test-model",
        "output": [
            {
                "id": "msg_integration",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": answer, "annotations": []}],
            }
        ],
    }


def _message(response: Response) -> dict[str, object]:
    assert response.status_code == 201
    data = response.json()
    MessageResponse.model_validate(data)
    assert data["status"] == "completed"
    assert data["error_code"] is None
    assert data["finished_at"] is not None
    assert data["request_id"] == response.headers["X-Request-ID"]
    assert UUID(data["request_id"]).version == 4
    return data


@pytest.mark.parametrize(
    ("scenario", "expected_status", "expected_code", "max_retries"),
    [
        ("success", 201, None, 0),
        ("empty", 502, "AI_UNAVAILABLE", 0),
        ("incomplete", 502, "AI_UNAVAILABLE", 0),
        ("timeout", 504, "AI_TIMEOUT", 0),
        ("deadline", 504, "AI_TIMEOUT", 0),
        ("connection", 502, "AI_UNAVAILABLE", 0),
        ("malformed", 502, "AI_UNAVAILABLE", 0),
        ("401", 503, "AI_CONFIGURATION_ERROR", 0),
        ("403", 503, "AI_CONFIGURATION_ERROR", 0),
        ("404", 503, "AI_CONFIGURATION_ERROR", 0),
        ("429", 502, "AI_UNAVAILABLE", 0),
        ("500", 502, "AI_UNAVAILABLE", 0),
        ("success", 201, None, None),
        ("recover_500", 201, None, 4),
        ("recover_connection", 201, None, 4),
        ("recover_timeout", 201, None, 4),
        ("recover_retry_after", 201, None, 4),
        ("exhaust_408", 502, "AI_UNAVAILABLE", 4),
        ("exhaust_409", 502, "AI_UNAVAILABLE", 4),
        ("exhaust_429", 502, "AI_UNAVAILABLE", 4),
        ("exhaust_500", 502, "AI_UNAVAILABLE", 4),
        ("exhaust_503", 502, "AI_UNAVAILABLE", 4),
        ("exhaust_connection", 502, "AI_UNAVAILABLE", 4),
        ("exhaust_timeout", 504, "AI_TIMEOUT", 4),
        ("400", 502, "AI_UNAVAILABLE", 4),
        ("401", 503, "AI_CONFIGURATION_ERROR", 4),
        ("403", 503, "AI_CONFIGURATION_ERROR", 4),
        ("404", 503, "AI_CONFIGURATION_ERROR", 4),
        ("422", 502, "AI_UNAVAILABLE", 4),
        ("empty", 502, "AI_UNAVAILABLE", 4),
        ("incomplete", 502, "AI_UNAVAILABLE", 4),
        ("malformed", 502, "AI_UNAVAILABLE", 4),
        ("retry_forbidden", 502, "AI_UNAVAILABLE", 4),
        ("retry_budget", 504, "AI_TIMEOUT", 4),
        ("retry_call_deadline", 504, "AI_TIMEOUT", 4),
        ("retry_wait_deadline", 504, "AI_TIMEOUT", 4),
    ],
)
def test_app_sdk_and_database_integration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    scenario: str,
    expected_status: int,
    expected_code: ErrorCode | None,
    max_retries: int | None,
) -> None:
    """SDK의 응답·예외가 API 응답·DB 기록·문맥·로그에 연결되는지 확인한다.

    Args:
        tmp_path: 운영 DB와 분리한 임시 SQLite 파일 경로.
        monkeypatch: 테스트용 인증·설정·SDK 전송과 DB 의존성을 연결할 도구.
        caplog: 원문 노출과 요청 식별자를 확인할 로그 수집 도구.
        scenario: 모의 HTTP 응답 또는 네트워크 오류의 종류.
        expected_status: 질문 전송 API에 기대하는 HTTP 상태.
        expected_code: 실패 시 저장·반환해야 하는 오류 코드.
        max_retries: 직접 재시도 횟수. None이면 설정 기본값을 검증한다.
    """
    timeout = (
        0.1
        if scenario in {"deadline", "retry_call_deadline", "retry_wait_deadline"}
        else 30
    )
    if max_retries is None:
        monkeypatch.delenv("AI_MAX_RETRIES", raising=False)
    settings = Settings(
        _env_file=None,
        openai_api_key="test-only",
        openai_model="test-model",
        ai_timeout_seconds=timeout,
        jwt_secret_key="test-only-chat-integration-secret-123456789",
    )
    if max_retries is not None:
        settings.ai_max_retries = max_retries
    else:
        assert settings.ai_max_retries == 4
    if scenario == "recover_retry_after":
        first_attempts = 2
    elif scenario.startswith(("recover_", "exhaust_")):
        first_attempts = 5
    else:
        first_attempts = 1
    real_sleep = asyncio.sleep

    async def wait(delay: float) -> None:
        if scenario == "retry_wait_deadline":
            await real_sleep(0.2)

    sleep = AsyncMock(side_effect=wait)
    monkeypatch.setattr(
        "app.clients.ai.asyncio",
        SimpleNamespace(
            get_running_loop=asyncio.get_running_loop,
            timeout=asyncio.timeout,
            sleep=sleep,
        ),
    )
    monkeypatch.setattr("app.clients.ai.uniform", lambda low, high: 1.0)
    monkeypatch.setattr("app.main.settings", settings)
    monkeypatch.setitem(
        app.dependency_overrides, get_current_user_id, lambda: 2**40 + 7
    )
    logger = logging.getLogger("app.events")
    monkeypatch.setattr(logger, "handlers", [caplog.handler])
    monkeypatch.setattr(logger, "propagate", False)
    caplog.set_level(logging.INFO, logger="app.events")
    sdk_requests: list[httpx2.Request] = []
    sdk_connections: list[httpx2.AsyncClient] = []
    request_sessions: list[AsyncSession] = []
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}"
    expected_messages: list[dict[str, object]] = []
    pending_ids: list[UUID] = []

    async def run() -> None:
        engine = create_async_engine(database_url)
        event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def create_tables() -> None:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

        monkeypatch.setattr("app.main.create_db_and_tables", create_tables)
        monkeypatch.setattr("app.main.engine", engine)

        async def test_db() -> AsyncGenerator[AsyncSession, None]:
            async with sessions() as session:
                request_sessions.append(session)
                yield session

        monkeypatch.setitem(app.dependency_overrides, get_db, test_db)

        async def respond(request: httpx2.Request) -> httpx2.Response:
            sdk_requests.append(request)
            payload = json.loads(request.content)
            assert not request_sessions[-1].in_transaction()
            async with sessions() as session:
                pending_rows = list(
                    (await session.scalars(
                        select(ChatLog).where(ChatLog.status == "pending")
                    )).all()
                )
                assert len(pending_rows) == 1
                pending = pending_rows[0]
                pending_ids.append(pending.request_id)
                assert str(pending.request_id) == caplog.records[-1].request_id
                assert pending.question == payload["input"][-1]["content"]
                assert pending.answer is pending.finished_at is None
            failure = scenario.removeprefix("recover_").removeprefix("exhaust_")
            should_fail = not scenario.startswith("recover_") or (
                len(sdk_requests) < first_attempts
            )
            if failure == "timeout" and should_fail:
                raise httpx2.ReadTimeout("hidden SDK timeout", request=request)
            if scenario in {"deadline", "retry_call_deadline"}:
                await real_sleep(0.2)
            if failure == "connection" and should_fail:
                raise httpx2.ConnectError("hidden SDK connection", request=request)
            if scenario == "malformed":
                return httpx2.Response(
                    200,
                    content=b"{",
                    headers={"content-type": "application/json"},
                )
            if failure.isdigit() and should_fail:
                return httpx2.Response(
                    int(failure), json={"error": {"message": "hidden SDK error"}}
                )
            headers = {
                "recover_retry_after": {"Retry-After": "1.5"},
                "retry_forbidden": {"x-should-retry": "false"},
                "retry_budget": {"Retry-After": "30"},
                "retry_wait_deadline": {"Retry-After": "0.001"},
            }
            if scenario in headers and should_fail:
                return httpx2.Response(
                    500,
                    headers=headers[scenario],
                    json={"error": {"message": "hidden SDK error"}},
                )
            return httpx2.Response(
                200,
                json=_sdk_response(
                    "incomplete" if scenario == "incomplete" else "completed",
                    "  " if scenario == "empty" else f"통합 답변{len(sdk_requests)}",
                ),
            )

        def sdk_factory(
            *, api_key: str, timeout: float, max_retries: int
        ) -> AsyncOpenAI:
            assert api_key == "test-only"
            assert timeout == settings.ai_timeout_seconds
            assert max_retries == 0
            connection = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
            sdk_connections.append(connection)
            return AsyncOpenAI(
                api_key=api_key,
                timeout=timeout,
                max_retries=0,
                http_client=connection,
            )

        monkeypatch.setattr("app.clients.ai.AsyncOpenAI", sdk_factory)
        async with lifespan(app):
            async with sessions() as session:
                session.add(
                    User(
                        id=2**40 + 7,
                        username="sdk_owner",
                        password_hash="test-only",
                        name="통합 회원",
                    )
                )
                await session.commit()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                created = await client.post("/api/v1/chats")
                assert created.status_code == 201
                path = f"/api/v1/chats/{created.json()['chat_id']}"
                first = await client.post(
                    path + "/messages", json={"question": "  첫 통합 질문  "}
                )
                assert first.status_code == expected_status
                assert len(sdk_requests) == first_attempts
                assert len(set(pending_ids)) == 1
                payloads = [json.loads(request.content) for request in sdk_requests]
                assert all(payload == payloads[0] for payload in payloads)
                assert len(sdk_connections) == 1
                assert not sdk_connections[0].is_closed
                if expected_code is None:
                    first_message = _message(first)
                    assert first_message["question"] == "첫 통합 질문"
                    assert first_message["answer"] == f"통합 답변{first_attempts}"
                    assert first_message["request_id"] == str(pending_ids[0])
                    second = await client.post(
                        path + "/messages", json={"question": "다음 통합 질문"}
                    )
                    second_message = _message(second)
                    assert second_message["answer"] == f"통합 답변{first_attempts + 1}"
                    assert first_message["request_id"] != second_message["request_id"]
                    expected_messages.extend([first_message, second_message])
                    second_payload = json.loads(sdk_requests[-1].content)
                    assert second_payload["input"] == [
                        {"role": "user", "content": "첫 통합 질문"},
                        {"role": "assistant", "content": f"통합 답변{first_attempts}"},
                        {"role": "user", "content": "다음 통합 질문"},
                    ]
                else:
                    error = first.json()["error"]
                    assert error["code"] == expected_code
                    assert error["request_id"] == first.headers["X-Request-ID"]
                    assert "hidden SDK" not in first.text
                detail = await client.get(path)
                assert detail.status_code == 200
                if expected_code is None:
                    assert detail.json()["messages"] == sorted(
                        expected_messages,
                        key=lambda message: (
                            message["created_at"],
                            message["request_id"],
                        ),
                    )
                else:
                    messages = detail.json()["messages"]
                    assert len(messages) == 1
                    message = messages[0]
                    MessageResponse.model_validate(message)
                    assert message["question"] == "첫 통합 질문"
                    assert message["request_id"] == first.headers["X-Request-ID"]
                    assert message["request_id"] == str(pending_ids[0])
                    assert message["status"] == "failed"
                    assert message["answer"] is None
                    assert message["error_code"] == expected_code
                    assert message["finished_at"] is not None
                    expected_messages.append(message)
                listing = await client.get("/api/v1/chats")
                assert listing.status_code == 200
                assert listing.json()["items"] == [created.json()]
                if expected_code is None:
                    health = await client.get("/health")
                    assert health.status_code == 200
                    assert health.json() == {"status": "ok"}
                    invalid = await client.post(
                        path + "/messages", json={"question": "   "}
                    )
                    assert invalid.status_code == 422
                    assert invalid.json()["error"]["code"] == "INVALID_INPUT"
                    monkeypatch.setitem(
                        app.dependency_overrides, get_current_user_id, lambda: 2**40 + 8
                    )
                    other_owner = await client.post(
                        path + "/messages", json={"question": "타인 채팅방 질문"}
                    )
                    assert other_owner.status_code == 404
                    assert other_owner.json()["error"]["code"] == "CHAT_NOT_FOUND"
                    def reject_auth() -> int:
                        """인증 실패를 재현한다."""
                        raise APIError("UNAUTHORIZED")

                    monkeypatch.setitem(
                        app.dependency_overrides, get_current_user_id, reject_auth
                    )
                    unauthorized = await client.post(
                        path + "/messages", json={"question": "미인증 질문"}
                    )
                    assert unauthorized.status_code == 401
                    assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED"
                    assert len(sdk_requests) == first_attempts + 1
        assert len(sdk_connections) == 1
        assert sdk_connections[0].is_closed

        reopened = create_async_engine(database_url)
        try:
            reopened_sessions = async_sessionmaker(reopened)
            async with reopened_sessions() as session:
                chats = list((await session.scalars(select(Chat))).all())
                messages = list((await session.scalars(select(ChatLog))).all())
                assert len(chats) == 1 and chats[0].user_id == 2**40 + 7
                owner = await session.get(User, chats[0].user_id)
                assert owner is not None and owner.username == "sdk_owner"
                assert len(messages) == len(expected_messages)
                by_id = {str(message.request_id): message for message in messages}
                for expected in expected_messages:
                    stored = by_id[expected["request_id"]]
                    assert stored.model == "test-model"
                    assert (
                        MessageResponse.model_validate(stored).model_dump(mode="json")
                        == expected
                    )
        finally:
            await reopened.dispose()

    asyncio.run(run())
    assert len(sdk_requests) == first_attempts + (1 if expected_code is None else 0)
    if scenario == "recover_retry_after":
        expected_delays = [1.5]
    elif scenario == "retry_wait_deadline":
        expected_delays = [0.001]
    else:
        expected_delays = [1.0, 2.0, 4.0, 8.0][:first_attempts - 1]
    assert [call.args[0] for call in sleep.await_args_list] == expected_delays
    assert all(connection.is_closed for connection in sdk_connections)
    for request in sdk_requests:
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["store"] is False
    formatter = EventLogFormatter()
    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    for private_text in ("첫 통합 질문", "다음 통합 질문", "통합 답변", "hidden SDK"):
        assert private_text not in rendered
    for message in expected_messages:
        events = [
            record.getMessage()
            for record in caplog.records
            if record.request_id == message["request_id"]
        ]
        assert events.count("db_save_succeeded") == 2
        assert events.count("ai_call_started") == 1
        outcome = (
            "ai_call_succeeded" if expected_code is None else "ai_call_failed"
        )
        assert events.count(outcome) == 1
