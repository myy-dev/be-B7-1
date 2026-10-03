"""HTTP 공통 처리와 요청별 로그 식별자의 일관성을 검증한다."""

import asyncio
import json
import unittest
from collections.abc import AsyncGenerator
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import RequestId
from app.core.database import get_db
from app.core.errors import ERROR_STATUS_CODES, APIError, configure_request_processing
from app.core.logging import EventLogFormatter, log_event
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
        log_event("ai_started")
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


class RequestProcessingTests(unittest.TestCase):
    """실제 HTTP 요청에서 오류 형식·헤더·로그의 일관성을 확인한다."""

    def test_server_generates_unique_request_ids(self) -> None:
        """클라이언트 값을 사용하지 않고 요청마다 새 UUID4를 생성한다."""
        client = TestClient(_test_app())
        supplied_id = "16fd2706-8baf-433b-82eb-8c7fada847da"
        with self.assertLogs("app.events", level="INFO") as logs:
            first = client.get("/identity", headers={"X-Request-ID": supplied_id})
            second = client.get("/identity")
        request_id = first.json()["request_id"]
        self.assertEqual(UUID(request_id).version, 4)
        self.assertEqual(first.json()["context_id"], request_id)
        self.assertEqual(first.headers["X-Request-ID"], request_id)
        self.assertNotEqual(request_id, supplied_id)
        self.assertNotEqual(request_id, second.json()["request_id"])
        ids = {record.request_id for record in logs.records}
        self.assertEqual(ids, {request_id, second.json()["request_id"]})

    def test_specified_errors_share_response_and_log_id(self) -> None:
        """명세의 모든 오류가 올바른 상태와 동일한 요청 ID를 사용한다."""
        client = TestClient(_test_app())
        for code, status_code in ERROR_STATUS_CODES.items():
            with self.subTest(code=code), self.assertLogs("app.events") as logs:
                response = client.get(f"/error/{code}")
                error = response.json()["error"]
                self.assertEqual(response.status_code, status_code)
                self.assertEqual(set(error), {"code", "message", "request_id"})
                self.assertEqual(error["code"], code)
                self.assertEqual(error["request_id"], response.headers["X-Request-ID"])
                self.assertEqual(UUID(error["request_id"]).version, 4)
            self.assertTrue(
                all(record.request_id == error["request_id"] for record in logs.records)
            )

    def test_validation_errors_do_not_expose_input(self) -> None:
        """잘못된 JSON·본문·경로 입력의 원문을 응답과 이벤트 로그에서 제외한다."""
        client = TestClient(_test_app())
        for path, arguments in (
            ("/validation", {"json": {"count": "private question"}}),
            (
                "/validation",
                {
                    "content": '{"count": "private question"',
                    "headers": {"Content-Type": "application/json"},
                },
            ),
            ("/error/not-a-code", None),
        ):
            with self.subTest(path=path), self.assertLogs("app.events") as logs:
                response = (
                    client.get(path)
                    if arguments is None
                    else client.post(path, **arguments)
                )
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["error"]["code"], "INVALID_INPUT")
            self.assertNotIn("private question", response.text)
            self.assertNotIn("private question", "\n".join(logs.output))
            self.assertEqual(
                response.json()["error"]["request_id"], response.headers["X-Request-ID"]
            )

    def test_auth_error_keeps_challenge_header(self) -> None:
        """인증 원문을 감추면서 인증 프로토콜에 필요한 헤더는 유지한다."""
        client = TestClient(_test_app())
        with self.assertLogs("app.events") as logs:
            response = client.get("/unauthorized")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "UNAUTHORIZED")
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
        self.assertNotIn("private authentication detail", response.text)
        self.assertNotIn("private authentication detail", "\n".join(logs.output))

    def test_database_error_redacts_sql_and_parameters(self) -> None:
        """DB 오류의 SQL·매개변수·원본 메시지를 출력하지 않는다."""
        client = TestClient(_test_app())
        with self.assertLogs("app.events") as logs:
            response = client.get("/database-error")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "DB_ERROR")
        formatter = EventLogFormatter()
        rendered = "\n".join(formatter.format(record) for record in logs.records)
        self.assertNotIn("private", response.text + rendered)
        failed = [json.loads(line) for line in rendered.splitlines()]
        self.assertTrue(any(item["event"] == "db_failed" for item in failed))

    def test_unexpected_error_is_logged_and_reraised(self) -> None:
        """명세에 없는 예외를 DB 오류로 오분류하지 않고 원문 없는 로그를 남긴다."""
        client = TestClient(_test_app())
        with self.assertLogs("app.events") as logs, self.assertRaises(RuntimeError):
            client.get("/unexpected-error")
        self.assertEqual(logs.records[-1].getMessage(), "request_failed")
        self.assertEqual(logs.records[-1].exception_type, "RuntimeError")
        self.assertNotIn("private runtime detail", "\n".join(logs.output))

    def test_existing_internal_error_has_matching_request_id(self) -> None:
        """main의 일반 서버 오류 응답과 AI 요청 로그의 식별자가 일치한다."""
        client = TestClient(_test_app(), raise_server_exceptions=False)
        with self.assertLogs("app.events") as logs:
            response = client.get("/unexpected-error")
        self.assertEqual(response.status_code, 500)
        error = response.json()["error"]
        self.assertEqual(error["code"], "INTERNAL_ERROR")
        self.assertEqual(error["request_id"], response.headers["X-Request-ID"])
        self.assertEqual(UUID(error["request_id"]).version, 4)
        self.assertTrue(
            all(record.request_id == error["request_id"] for record in logs.records)
        )
        self.assertEqual(logs.records[-1].error_code, "INTERNAL_ERROR")
        self.assertNotIn("private runtime detail", response.text)

    def test_existing_admin_routes_keep_error_contract(self) -> None:
        """설정 파일을 읽지 않고 실제 관리자 라우터와 오류 형식을 검증한다."""
        from app.api.v1.admin_deps import get_admin_service
        from app.main import app
        from app.repositories.admin_mock import (
            MockChatLogRepository,
            MockSessionRepository,
            MockUserRepository,
        )
        from app.repositories.admin_system_log import SystemLogFileRepository
        from app.services.admin_service import AdminService

        with TemporaryDirectory() as directory:
            service = AdminService(
                users=MockUserRepository(),
                chat_logs=MockChatLogRepository(),
                sessions=MockSessionRepository(),
                system_logs=SystemLogFileRepository(
                    str(Path(directory) / "system.jsonl")
                ),
            )
            app.dependency_overrides[get_admin_service] = lambda: service
            try:
                client = TestClient(app)
                with self.assertLogs("app.events") as logs:
                    listing = client.get("/admin/users")
                    missing = client.get("/admin/users/9999")
                self.assertEqual(listing.status_code, 200)
                self.assertGreaterEqual(listing.json()["total"], 1)
                self.assertEqual(missing.status_code, 404)
                error = missing.json()["error"]
                self.assertEqual(error["code"], "USER_NOT_FOUND")
                self.assertEqual(error["request_id"], missing.headers["X-Request-ID"])
                received = [
                    record
                    for record in logs.records
                    if record.getMessage() == "request_received"
                ]
                self.assertEqual(len(received), 2)
                self.assertEqual(logs.records[-1].error_code, "USER_NOT_FOUND")
            finally:
                app.dependency_overrides.pop(get_admin_service)


class RequestIsolationTests(unittest.IsolatedAsyncioTestCase):
    """동시 요청과 실제 앱의 DB 의존성 연결을 확인한다."""

    async def test_concurrent_requests_keep_separate_contexts(self) -> None:
        """동시에 실행된 요청의 식별자가 서로 섞이지 않고 종료 후 정리된다."""
        transport = ASGITransport(app=_test_app())
        with self.assertLogs("app.events") as logs:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                responses = await asyncio.gather(
                    *(client.get("/identity") for _ in range(8))
                )
        ids = {response.json()["request_id"] for response in responses}
        self.assertEqual(len(ids), 8)
        for response in responses:
            self.assertEqual(
                response.json()["request_id"], response.json()["context_id"]
            )
        self.assertEqual({record.request_id for record in logs.records}, ids)
        self.assertIsNone(request_id_context.get())

    async def test_context_is_reset_after_exception(self) -> None:
        """예외 발생 후에도 호출자의 요청 컨텍스트가 비어 있는지 확인한다."""
        transport = ASGITransport(app=_test_app())
        with self.assertLogs("app.events"), self.assertRaises(RuntimeError):
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                await client.get("/unexpected-error")
        self.assertIsNone(request_id_context.get())

    async def test_application_health_with_isolated_database(self) -> None:
        """앱의 공통 처리와 DB 별칭이 실제 SQLite 세션으로 동작하는지 확인한다."""
        from app.main import app

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = async_sessionmaker(engine)

        async def test_db() -> AsyncGenerator[AsyncSession, None]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_db] = test_db
        try:
            with self.assertLogs("app.events"):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok"})
            self.assertEqual(UUID(response.headers["X-Request-ID"]).version, 4)
        finally:
            app.dependency_overrides.pop(get_db)
            await engine.dispose()
