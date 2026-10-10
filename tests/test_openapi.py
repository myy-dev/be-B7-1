"""Swagger 오류 예시와 실제 공통 오류 응답의 일치를 검증한다."""

from collections.abc import Iterator
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_ai_client, get_chat_service, get_current_user_id
from app.api.error_responses import error_response
from app.api.v1.endpoints.chat import router
from app.core.errors import APIError, configure_request_processing, internal_error
from app.models.chat import Chat
from app.schemas.error import ErrorCode, ErrorResponse
from app.services.chat_service import ChatService

CHAT_ID = "00000000-0000-4000-8000-000000000001"
CHAT_PATH = "/api/v1/chats/{chat_id}"
MESSAGE_PATH = CHAT_PATH + "/messages"
MESSAGE_URL = f"/api/v1/chats/{CHAT_ID}/messages"


@pytest.fixture
def docs_client() -> Iterator[TestClient]:
    """실제 서비스와 모의 저장소를 연결한 문서 검증용 앱을 제공한다.

    Yields:
        DB와 외부 AI를 호출하지 않는 HTTP 클라이언트.
    """
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    configure_request_processing(app)
    app.dependency_overrides[get_current_user_id] = lambda: 1
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_errors_use_common_schema_and_named_examples(docs_client: TestClient) -> None:
    """모든 오류 응답에 실제 상태별 예시와 공통 스키마가 포함된다."""
    schema = docs_client.get("/openapi.json").json()
    for route in docs_client.app.routes:
        if isinstance(route, APIRoute):
            assert all(int(status) >= 400 for status in route.responses)
    for path in schema["paths"].values():
        for operation in path.values():
            for status, response in operation["responses"].items():
                if int(status) < 400:
                    continue
                media = response["content"]["application/json"]
                assert media["schema"]["$ref"] == "#/components/schemas/ErrorResponse"
                assert "example" not in media
                assert media["examples"]
                for code, example in media["examples"].items():
                    payload = ErrorResponse.model_validate(example["value"])
                    assert payload.error.code == code
                    if code == "UNAUTHORIZED":
                        assert status == "401"
    for path, method in [
        ("/api/v1/chats", "post"),
        (CHAT_PATH, "get"),
        (CHAT_PATH, "delete"),
    ]:
        examples = schema["paths"][path][method]["responses"]["500"]["content"][
            "application/json"
        ]["examples"]
        assert set(examples) == {"DB_ERROR", "INTERNAL_ERROR"}
    assert docs_client.get("/docs").status_code == 200


def test_question_documents_length_limit(docs_client: TestClient) -> None:
    """질문 요청의 길이 제한과 설명이 OpenAPI에 반영된다."""
    schema = docs_client.get("/openapi.json").json()
    request_schema = schema["paths"][MESSAGE_PATH]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert request_schema["$ref"] == "#/components/schemas/MessageCreateRequest"
    question = schema["components"]["schemas"]["MessageCreateRequest"]["properties"][
        "question"
    ]
    assert question["minLength"] == 1
    assert question["maxLength"] == 1000
    assert "앞뒤 공백 제거 후 1~1,000자" in question["description"]


def test_delete_documents_no_body_and_expected_errors(docs_client: TestClient) -> None:
    """삭제 API는 요청·성공 본문 없이 인증과 예상 오류를 문서화한다."""
    operation = docs_client.get("/openapi.json").json()["paths"][CHAT_PATH]["delete"]
    assert "requestBody" not in operation
    assert set(operation["responses"]) == {"204", "401", "404", "422", "500"}
    assert "content" not in operation["responses"]["204"]
    assert operation["security"] == [{"HTTPBearer": []}]
    parameter = operation["parameters"][0]
    assert parameter["name"] == "chat_id"
    assert parameter["in"] == "path"
    assert parameter["schema"]["format"] == "uuid"


@pytest.mark.parametrize(
    ("path", "method", "url", "code", "status"),
    [
        (CHAT_PATH, "get", f"/api/v1/chats/{CHAT_ID}", "CHAT_NOT_FOUND", 404),
        (CHAT_PATH, "get", "/api/v1/chats/invalid", "INVALID_INPUT", 422),
        (CHAT_PATH, "delete", f"/api/v1/chats/{CHAT_ID}", "CHAT_NOT_FOUND", 404),
        (CHAT_PATH, "delete", "/api/v1/chats/invalid", "INVALID_INPUT", 422),
        (CHAT_PATH, "delete", f"/api/v1/chats/{CHAT_ID}", "DB_ERROR", 500),
        (CHAT_PATH, "delete", f"/api/v1/chats/{CHAT_ID}", "INTERNAL_ERROR", 500),
        ("/api/v1/chats", "post", "/api/v1/chats", "DB_ERROR", 500),
        ("/api/v1/chats", "post", "/api/v1/chats", "INTERNAL_ERROR", 500),
        (MESSAGE_PATH, "post", MESSAGE_URL, "AI_UNAVAILABLE", 502),
        (MESSAGE_PATH, "post", MESSAGE_URL, "AI_CONFIGURATION_ERROR", 503),
        (MESSAGE_PATH, "post", MESSAGE_URL, "AI_TIMEOUT", 504),
        (MESSAGE_PATH, "post", MESSAGE_URL, "INVALID_INPUT", 422),
    ],
)
def test_examples_match_real_services_and_handlers(
    docs_client: TestClient, path: str, method: str, url: str, code: str, status: int
) -> None:
    """서비스·핸들러의 상태·코드·문구가 Swagger 예시와 일치한다."""
    repository = AsyncMock()
    repository.get_by_id_and_user.return_value = None
    repository.soft_delete.return_value = False
    repository.list_recent_completed.return_value = []
    service = ChatService(repository)
    docs_client.app.dependency_overrides[get_chat_service] = lambda: service
    ai = AsyncMock()
    ai.model = "test-only"
    docs_client.app.dependency_overrides[get_ai_client] = lambda: ai
    body = {"question": "질문"}
    saving = repository.soft_delete if method == "delete" else repository.create
    if code == "DB_ERROR":
        saving.side_effect = OperationalError("test", {}, RuntimeError())
    elif code == "INTERNAL_ERROR":
        saving.side_effect = RuntimeError("private test error")
    elif code.startswith("AI_"):
        repository.get_by_id_and_user.return_value = Chat(user_id=1)
        ai.generate_answer.side_effect = APIError(cast(ErrorCode, code))
    elif code == "INVALID_INPUT":
        body = {"question": "   "}
    response = docs_client.request(method, url, json=body if method == "post" else None)
    assert response.status_code == status
    actual = ErrorResponse.model_validate(response.json()).model_dump(mode="json")
    operation = docs_client.get("/openapi.json").json()["paths"][path][method]
    example = operation["responses"][str(status)]["content"]["application/json"][
        "examples"
    ][code]["value"]
    assert actual["error"]["code"] == example["error"]["code"]
    assert actual["error"]["message"] == example["error"]["message"]
    assert actual["error"]["request_id"] == response.headers["X-Request-ID"]


def test_response_helper_rejects_mixed_statuses() -> None:
    """다른 HTTP 상태의 오류를 한 응답으로 잘못 묶을 수 없다."""
    with pytest.raises(ValueError):
        error_response(APIError("CHAT_NOT_FOUND"), internal_error())
