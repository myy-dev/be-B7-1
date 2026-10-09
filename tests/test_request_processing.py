"""HTTP 공통 처리와 요청별 로그 식별자의 일관성을 검증한다."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import RequestId
from app.core.database import get_db
from app.core.errors import (
    ERROR_STATUS_CODES,
    APIError,
    configure_request_processing,
)
from app.core.logging import EventLogFormatter, configure_logging, log_event
from app.core.request_context import request_id_context
from app.schemas.error import ErrorCode


class _Input(BaseModel):
    count: int


def _test_app() -> FastAPI:
    app = FastAPI()
    configure_request_processing(app)

    @app.get("/identity")
    async def identity(request_id: RequestId) -> dict[str, str]:
        await asyncio.sleep(0)
        log_event("ai_call_started")
        return {
            "request_id": str(request_id),
            "context_id": str(request_id_context.get()),
        }

    @app.get("/error/{code}")
    async def expected_error(code: ErrorCode) -> None:
        raise APIError(code)

    @app.post("/validation")
    async def validation(payload: _Input) -> dict[str, int]:
        return {"count": payload.count}

    @app.get("/unauthorized")
    async def unauthorized() -> None:
        raise HTTPException(
            status_code=401,
            detail="private authentication detail",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/database-error")
    async def database_error() -> None:
        raise OperationalError(
            "SQL with private question",
            {"question": "private question"},
            RuntimeError("private database detail"),
        )

    @app.get("/unexpected-error")
    async def unexpected_error() -> None:
        raise RuntimeError("private runtime detail")

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """공통 처리를 연결한 테스트 앱의 HTTP 클라이언트를 제공한다.

    Yields:
        테스트 종료 시 연결을 정리하는 HTTP 클라이언트.
    """
    test_client = TestClient(_test_app())
    try:
        yield test_client
    finally:
        test_client.close()


@pytest.fixture
def event_logs(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> pytest.LogCaptureFixture:
    """상위 로거에 전달하지 않는 이벤트 로그를 caplog로 수집한다.

    Args:
        caplog: pytest 로그 수집 도구.
        monkeypatch: 테스트 종료 후 로거 설정을 복원할 도구.

    Returns:
        현재 테스트의 이벤트 로그를 수집하는 도구.
    """
    logger = logging.getLogger("app.events")
    monkeypatch.setattr(logger, "handlers", [caplog.handler])
    monkeypatch.setattr(logger, "propagate", False)
    caplog.set_level(logging.INFO, logger="app.events")
    return caplog


def test_events_are_written_to_configured_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """설정한 시스템 로그 파일에 이벤트를 JSONL로 기록한다."""
    logger = logging.getLogger("app.events")
    monkeypatch.setattr(logger, "handlers", [])
    log_path = tmp_path / "logs" / "system.jsonl"
    request_id = UUID("16fd2706-8baf-433b-82eb-8c7fada847da")

    configure_logging(str(log_path))
    log_event(
        "ai_call_failed",
        request_id=request_id,
        user_id="7",
        error_code="AI_UNAVAILABLE",
        result="failure",
    )
    for handler in logger.handlers:
        handler.flush()

    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["event"] == "ai_call_failed"
    assert record["request_id"] == str(request_id)
    assert record["user_id"] == "7"
    assert record["error_code"] == "AI_UNAVAILABLE"
    for handler in logger.handlers:
        handler.close()


def test_server_generates_unique_request_ids(
    client: TestClient, event_logs: pytest.LogCaptureFixture
) -> None:
    """클라이언트 값을 사용하지 않고 요청마다 새 UUID4를 생성한다."""
    supplied_id = "16fd2706-8baf-433b-82eb-8c7fada847da"
    first = client.get("/identity", headers={"X-Request-ID": supplied_id})
    second = client.get("/identity")
    request_id = first.json()["request_id"]
    assert UUID(request_id).version == 4
    assert first.json()["context_id"] == request_id
    assert first.headers["X-Request-ID"] == request_id
    assert request_id != supplied_id
    assert request_id != second.json()["request_id"]
    ids = {record.request_id for record in event_logs.records}
    assert ids == {request_id, second.json()["request_id"]}


@pytest.mark.parametrize(("code", "status_code"), ERROR_STATUS_CODES.items())
def test_specified_errors_share_response_and_log_id(
    client: TestClient,
    event_logs: pytest.LogCaptureFixture,
    code: ErrorCode,
    status_code: int,
) -> None:
    """명세의 모든 오류가 올바른 상태와 동일한 요청 ID를 사용한다."""
    response = client.get(f"/error/{code}")
    error = response.json()["error"]
    assert response.status_code == status_code
    assert set(error) == {"code", "message", "request_id"}
    assert error["code"] == code
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert UUID(error["request_id"]).version == 4
    assert event_logs.records
    assert all(
        record.request_id == error["request_id"] for record in event_logs.records
    )


@pytest.mark.parametrize("scenario", ["invalid-type", "invalid-json", "invalid-path"])
def test_validation_errors_do_not_expose_input(
    client: TestClient, event_logs: pytest.LogCaptureFixture, scenario: str
) -> None:
    """잘못된 JSON·본문·경로 입력의 원문을 응답과 이벤트 로그에서 제외한다."""
    match scenario:
        case "invalid-type":
            response = client.post("/validation", json={"count": "private question"})
        case "invalid-json":
            response = client.post(
                "/validation",
                content='{"count": "private question"',
                headers={"Content-Type": "application/json"},
            )
        case "invalid-path":
            response = client.get("/error/not-a-code")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"
    assert "private question" not in response.text
    assert "private question" not in event_logs.text
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_auth_error_keeps_challenge_header(
    client: TestClient, event_logs: pytest.LogCaptureFixture
) -> None:
    """인증 원문을 감추면서 인증 프로토콜에 필요한 헤더는 유지한다."""
    response = client.get("/unauthorized")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "private authentication detail" not in response.text
    assert "private authentication detail" not in event_logs.text


def test_database_error_redacts_sql_and_parameters(
    client: TestClient, event_logs: pytest.LogCaptureFixture
) -> None:
    """DB 오류의 SQL·매개변수·원본 메시지를 출력하지 않는다."""
    response = client.get("/database-error")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "DB_ERROR"
    formatter = EventLogFormatter()
    rendered = "\n".join(formatter.format(record) for record in event_logs.records)
    assert "private" not in response.text + rendered
    failed = [json.loads(line) for line in rendered.splitlines()]
    assert any(item["event"] == "db_save_failed" for item in failed)


def test_unexpected_error_is_logged_and_reraised(
    client: TestClient, event_logs: pytest.LogCaptureFixture
) -> None:
    """명세에 없는 예외를 DB 오류로 오분류하지 않고 원문 없는 로그를 남긴다."""
    with pytest.raises(RuntimeError):
        client.get("/unexpected-error")
    assert event_logs.records[-1].getMessage() == "request_failed"
    assert event_logs.records[-1].exception_type == "RuntimeError"
    assert "private runtime detail" not in event_logs.text


def test_existing_internal_error_has_matching_request_id(
    event_logs: pytest.LogCaptureFixture,
) -> None:
    """main의 일반 서버 오류 응답과 AI 요청 로그의 식별자가 일치한다."""
    with TestClient(_test_app(), raise_server_exceptions=False) as client:
        response = client.get("/unexpected-error")
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert UUID(error["request_id"]).version == 4
    assert all(
        record.request_id == error["request_id"] for record in event_logs.records
    )
    assert event_logs.records[-1].error_code == "INTERNAL_ERROR"
    assert "private runtime detail" not in response.text


def test_existing_admin_routes_keep_error_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_logs: pytest.LogCaptureFixture,
) -> None:
    """설정 파일을 읽지 않고 실제 관리자 라우터와 오류 형식을 검증한다."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base
    from app.main import app
    from app.models.user import User

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'proc.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def initialize():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(
                User(
                    username="proc_user",
                    password_hash="test-only",
                    name="처리",
                )
            )
            await session.commit()

    async def override_db():
        async with sessions() as session:
            yield session

    asyncio.run(initialize())
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    client = TestClient(app)
    try:
        listing = client.get("/api/v1/admin/users")
        missing = client.get("/api/v1/admin/users/9999")
    finally:
        client.close()
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1
    assert missing.status_code == 404
    error = missing.json()["error"]
    assert error["code"] == "USER_NOT_FOUND"
    assert error["request_id"] == missing.headers["X-Request-ID"]
    received = [
        record
        for record in event_logs.records
        if record.getMessage() == "request_received"
    ]
    assert len(received) == 2
    assert event_logs.records[-1].error_code == "USER_NOT_FOUND"


def test_concurrent_requests_keep_separate_contexts(
    event_logs: pytest.LogCaptureFixture,
) -> None:
    """동시에 실행된 요청의 식별자가 서로 섞이지 않고 종료 후 정리된다."""

    async def run() -> None:
        transport = ASGITransport(app=_test_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            responses = await asyncio.gather(
                *(client.get("/identity") for _ in range(8))
            )
        ids = {response.json()["request_id"] for response in responses}
        assert len(ids) == 8
        for response in responses:
            assert response.json()["request_id"] == response.json()["context_id"]
        assert {record.request_id for record in event_logs.records} == ids
        assert request_id_context.get() is None

    asyncio.run(run())


def test_context_is_reset_after_exception(event_logs: pytest.LogCaptureFixture) -> None:
    """예외 발생 후에도 호출자의 요청 컨텍스트가 비어 있는지 확인한다."""

    async def run() -> None:
        transport = ASGITransport(app=_test_app())
        with pytest.raises(RuntimeError):
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                await client.get("/unexpected-error")
        assert request_id_context.get() is None

    asyncio.run(run())
    assert event_logs.records[-1].getMessage() == "request_failed"


def test_application_health_with_isolated_database(
    event_logs: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """앱의 공통 처리와 DB 별칭이 실제 SQLite 세션으로 동작하는지 확인한다."""
    from app.main import app

    async def run() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = async_sessionmaker(engine)

        async def test_db() -> AsyncGenerator[AsyncSession, None]:
            async with factory() as session:
                yield session

        try:
            with monkeypatch.context() as context:
                context.setitem(app.dependency_overrides, get_db, test_db)
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
            assert UUID(response.headers["X-Request-ID"]).version == 4
        finally:
            await engine.dispose()

    asyncio.run(run())
    assert event_logs.records
