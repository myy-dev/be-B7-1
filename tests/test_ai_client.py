"""실제 SDK를 모의 HTTP 전송에 연결하여 답변과 오류 처리를 검증한다."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from fastapi import FastAPI, Request
from openai import AsyncOpenAI
from pydantic import ValidationError

import app.main as main
from app.api.dependencies import get_ai_client
from app.clients.openai import OpenAIClient
from app.core.config import Settings
from app.core.errors import APIError


def _response(
    status: str = "completed", answer: str = "AI 답변"
) -> dict[str, object]:
    return {
        "id": "resp_test", "object": "response", "created_at": 1,
        "status": status, "model": "test-model",
        "output": [{
            "id": "msg_test", "type": "message", "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": answer, "annotations": []}],
        }],
    }


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("success", None),
        ("empty", "AI_UNAVAILABLE"),
        ("incomplete", "AI_UNAVAILABLE"),
        ("timeout", "AI_TIMEOUT"),
        ("deadline", "AI_TIMEOUT"),
        ("connection", "AI_UNAVAILABLE"),
        ("malformed", "AI_UNAVAILABLE"),
        ("401", "AI_CONFIGURATION_ERROR"),
        ("403", "AI_CONFIGURATION_ERROR"),
        ("404", "AI_CONFIGURATION_ERROR"),
        ("429", "AI_UNAVAILABLE"),
        ("500", "AI_UNAVAILABLE"),
    ],
)
def test_sdk_request_response_and_error_mapping(
    monkeypatch: pytest.MonkeyPatch, scenario: str, expected_code: str | None
) -> None:
    """실제 SDK의 요청 본문·미완성 응답·오류 변환과 자동 재시도 금지를 검증한다."""
    requests: list[httpx2.Request] = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if scenario == "timeout":
            raise httpx2.ReadTimeout("hidden timeout", request=request)
        if scenario == "deadline":
            await asyncio.sleep(0.05)
        if scenario == "connection":
            raise httpx2.ConnectError("hidden connection", request=request)
        if scenario == "malformed":
            return httpx2.Response(
                200,
                content=b"{",
                headers={"content-type": "application/json"},
            )
        if scenario.isdigit():
            return httpx2.Response(
                int(scenario), json={"error": {"message": "hidden API error"}}
            )
        return httpx2.Response(200, json=_response(
            status="incomplete" if scenario == "incomplete" else "completed",
            answer="  " if scenario == "empty" else "AI 답변",
        ))

    transport = httpx2.MockTransport(respond)
    http_client = httpx2.AsyncClient(transport=transport)
    sdk = AsyncOpenAI(api_key="test-only", max_retries=0, http_client=http_client)
    constructor = MagicMock(return_value=sdk)
    monkeypatch.setattr("app.clients.openai.AsyncOpenAI", constructor)
    timeout = 0.01 if scenario == "deadline" else 30
    client = OpenAIClient("test-only", "test-model", timeout, max_retries=0)
    constructor.assert_called_once_with(
        api_key="test-only", timeout=timeout, max_retries=0
    )

    async def run() -> None:
        try:
            if expected_code is None:
                answer = await client.generate_answer("현재 질문", [("이전 질문", "답변")])
                assert answer == "AI 답변"
            else:
                with pytest.raises(APIError) as caught:
                    await client.generate_answer("현재 질문", [("이전 질문", "답변")])
                assert caught.value.code == expected_code
                assert "hidden" not in str(caught.value)
        finally:
            await client.close()

    asyncio.run(run())
    assert http_client.is_closed
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload["model"] == "test-model"
    assert payload["store"] is False
    assert payload["input"] == [
        {"role": "user", "content": "이전 질문"},
        {"role": "assistant", "content": "답변"},
        {"role": "user", "content": "현재 질문"},
    ]


@pytest.mark.parametrize(
    ("key", "model", "field"),
    [
        ("", "test-model", "openai_api_key"),
        (" \t\n", "test-model", "openai_api_key"),
        ("test-only", "", "openai_model"),
        ("test-only", " \t\n", "openai_model"),
    ],
)
def test_invalid_configuration_rejected(key: str, model: str, field: str) -> None:
    """AI 필수 설정의 빈 값은 서버 시작에 사용하는 설정 생성 시 거절한다."""
    with pytest.raises(ValidationError) as caught:
        Settings(
            _env_file=None,
            openai_api_key=key,
            openai_model=model,
            jwt_secret_key="test-only-ai-client-secret-123456789",
        )
    assert caught.value.errors()[0]["loc"] == (field,)


def test_retry_setting_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """재시도 환경변수가 없으면 기본값 4를 사용한다."""
    monkeypatch.delenv("AI_MAX_RETRIES", raising=False)
    settings = Settings(
        _env_file=None,
        openai_api_key="test-only",
        jwt_secret_key="test-only-ai-client-secret-123456789",
    )
    assert settings.ai_max_retries == 4


@pytest.mark.parametrize("value", ["0", "4", "7"])
def test_retry_setting_from_environment(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """0을 포함한 재시도 횟수를 환경변수에서 읽는다."""
    monkeypatch.setenv("AI_MAX_RETRIES", value)
    settings = Settings(
        _env_file=None,
        openai_api_key="test-only",
        jwt_secret_key="test-only-ai-client-secret-123456789",
    )
    assert settings.ai_max_retries == int(value)


@pytest.mark.parametrize("value", ["-1", "invalid", "1.5"])
def test_invalid_retry_setting_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """음수·문자열·소수 재시도 설정은 설정 생성 시 거절한다."""
    monkeypatch.setenv("AI_MAX_RETRIES", value)
    with pytest.raises(ValidationError) as caught:
        Settings(
            _env_file=None,
            openai_api_key="test-only",
            jwt_secret_key="test-only-ai-client-secret-123456789",
        )
    assert caught.value.errors()[0]["loc"] == ("ai_max_retries",)


@pytest.mark.parametrize("max_retries", [0, 4, 7])
def test_client_keeps_sdk_retries_disabled(
    monkeypatch: pytest.MonkeyPatch, max_retries: int
) -> None:
    """직접 재시도 설정을 보관하면서 SDK 재시도는 0으로 고정한다."""
    sdk = MagicMock()
    constructor = MagicMock(return_value=sdk)
    monkeypatch.setattr("app.clients.openai.AsyncOpenAI", constructor)
    client = OpenAIClient("test-only", "test-model", 30, max_retries)
    assert client.max_retries == max_retries
    constructor.assert_called_once_with(
        api_key="test-only", timeout=30, max_retries=0
    )


@pytest.mark.parametrize(
    "scenario", ["success", "create_error", "body_error", "close_error"]
)
@pytest.mark.parametrize("max_retries", [0, 4, 7])
def test_lifespan_reuses_client_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, scenario: str, max_retries: int
) -> None:
    """요청 간 재사용과 생성·실행·종료 오류에서도 자원 정리를 검증한다."""
    settings = Settings(
        _env_file=None,
        openai_api_key="test-only",
        openai_model="test-model",
        ai_max_retries=max_retries,
        jwt_secret_key="test-only-ai-client-secret-123456789",
    )
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "create_db_and_tables", AsyncMock())
    engine = MagicMock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr(main, "engine", engine)
    client = MagicMock(spec=OpenAIClient)
    client.close = AsyncMock()
    failure = RuntimeError("lifecycle failure")
    constructor = MagicMock(return_value=client)
    if scenario == "create_error":
        constructor.side_effect = failure
    elif scenario == "close_error":
        client.close.side_effect = failure
    monkeypatch.setattr(main, "OpenAIClient", constructor)
    app = FastAPI(lifespan=main.lifespan)

    async def run() -> None:
        async with main.lifespan(app):
            first = Request({"type": "http", "app": app})
            second = Request({"type": "http", "app": app})
            assert get_ai_client(first) is get_ai_client(second) is client
            client.close.assert_not_awaited()
            if scenario == "body_error":
                raise failure

    if scenario == "success":
        asyncio.run(run())
    else:
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(run())
        assert caught.value is failure
    constructor.assert_called_once_with("test-only", "test-model", 30, max_retries)
    engine.dispose.assert_awaited_once()
    if scenario == "create_error":
        client.close.assert_not_awaited()
    else:
        client.close.assert_awaited_once()
