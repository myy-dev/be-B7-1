"""실제 SDK를 모의 HTTP 전송에 연결하여 답변과 오류 처리를 검증한다."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from openai import AsyncOpenAI

from app.api.dependencies import get_ai_client
from app.clients.ai import AIClient
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
    monkeypatch.setattr("app.clients.ai.AsyncOpenAI", constructor)
    timeout = 0.01 if scenario == "deadline" else 30
    client = AIClient("test-only", "test-model", timeout)
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


@pytest.mark.parametrize(("key", "model"), [("", "test-model"), ("test-only", " ")])
def test_invalid_configuration_rejected_without_client(
    monkeypatch: pytest.MonkeyPatch, key: str, model: str
) -> None:
    """비어 있는 AI 설정은 SDK 생성 전에 고정 설정 오류로 반환한다."""
    settings = Settings(_env_file=None, openai_api_key=key, openai_model=model)
    monkeypatch.setattr("app.api.dependencies.get_settings", lambda: settings)
    constructor = MagicMock()
    monkeypatch.setattr("app.api.dependencies.AIClient", constructor)

    async def run() -> None:
        with pytest.raises(APIError) as caught:
            await anext(get_ai_client(1))
        assert caught.value.code == "AI_CONFIGURATION_ERROR"

    asyncio.run(run())
    constructor.assert_not_called()


def test_dependency_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """요청 의존성이 종료되면 SDK HTTP 자원을 정리한다."""
    settings = Settings(
        _env_file=None, openai_api_key="test-only", openai_model="test-model"
    )
    monkeypatch.setattr("app.api.dependencies.get_settings", lambda: settings)
    client = MagicMock(spec=AIClient)
    client.close = AsyncMock()
    monkeypatch.setattr("app.api.dependencies.AIClient", lambda *args: client)

    async def run() -> None:
        dependency = get_ai_client(1)
        assert await anext(dependency) is client
        await dependency.aclose()

    asyncio.run(run())
    client.close.assert_awaited_once()
