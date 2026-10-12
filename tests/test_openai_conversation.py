import asyncio
import json
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from openai import AsyncOpenAI

from app.clients.ai import DEFAULT_INSTRUCTIONS
from app.clients.openai import OpenAIClient
from app.core.errors import APIError


def _response() -> dict[str, object]:
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": "test-model",
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": "답변",
                        "annotations": [],
                    }
                ],
            }
        ],
    }


def _client(
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[[httpx2.Request], Awaitable[httpx2.Response]],
    *,
    timeout: float = 30,
    max_retries: int = 4,
) -> tuple[OpenAIClient, httpx2.AsyncClient]:
    connection = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    sdk = AsyncOpenAI(api_key="test-only", max_retries=0, http_client=connection)
    monkeypatch.setattr("app.clients.openai.AsyncOpenAI", MagicMock(return_value=sdk))
    return OpenAIClient("test-only", "test-model", timeout, max_retries), connection


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("success", None),
        ("timeout", "AI_TIMEOUT"),
        ("deadline", "AI_TIMEOUT"),
        ("connection", "AI_UNAVAILABLE"),
        ("malformed", "AI_UNAVAILABLE"),
        ("401", "AI_CONFIGURATION_ERROR"),
        ("403", "AI_CONFIGURATION_ERROR"),
        ("404", "AI_CONFIGURATION_ERROR"),
        ("429", "AI_UNAVAILABLE"),
        ("500", "AI_UNAVAILABLE"),
        ("missing_id", "AI_UNAVAILABLE"),
        ("empty_id", "AI_UNAVAILABLE"),
        ("blank_id", "AI_UNAVAILABLE"),
        ("null_id", "AI_UNAVAILABLE"),
        ("numeric_id", "AI_UNAVAILABLE"),
    ],
)
def test_conversation_creation_and_error_mapping(
    monkeypatch: pytest.MonkeyPatch, scenario: str, expected_code: str | None
) -> None:
    """Conversation 생성의 SDK 요청·오류 변환과 재시도 금지를 검증한다."""
    requests: list[httpx2.Request] = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if scenario == "timeout":
            raise httpx2.ReadTimeout("hidden timeout", request=request)
        if scenario == "deadline":
            await asyncio.sleep(0.2)
        if scenario == "connection":
            raise httpx2.ConnectError("hidden connection", request=request)
        if scenario == "malformed":
            return httpx2.Response(
                200, content=b"{", headers={"content-type": "application/json"}
            )
        if scenario.isdigit():
            return httpx2.Response(
                int(scenario), json={"error": {"message": "hidden failure"}}
            )
        payload: dict[str, object] = {
            "id": "conv_test", "object": "conversation", "created_at": 1
        }
        if scenario == "missing_id":
            del payload["id"]
        elif scenario == "empty_id":
            payload["id"] = ""
        elif scenario == "blank_id":
            payload["id"] = " \t"
        elif scenario == "null_id":
            payload["id"] = None
        elif scenario == "numeric_id":
            payload["id"] = 123
        return httpx2.Response(200, json=payload)

    timeout = 0.03 if scenario == "deadline" else 30
    client, connection = _client(monkeypatch, respond, timeout=timeout)

    async def run() -> None:
        try:
            if expected_code is None:
                assert await client.create_conversation() == "conv_test"
            else:
                with pytest.raises(APIError) as caught:
                    await client.create_conversation()
                assert caught.value.code == expected_code
                assert "hidden" not in str(caught.value)
        finally:
            await client.close()

    asyncio.run(run())
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/v1/conversations"
    assert json.loads(requests[0].content) == {}
    assert connection.is_closed


def test_same_conversation_receives_only_new_question_and_compaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """연속 요청에 같은 ID·새 질문·기본 프롬프트·압축 기준을 전달한다."""
    requests: list[httpx2.Request] = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=_response())

    client, connection = _client(monkeypatch, respond)

    async def run() -> None:
        try:
            for question in ["첫 질문", "다음 질문"]:
                assert await client.generate_answer(
                    question, [], conversation_id="conv_test"
                ) == "답변"
        finally:
            await client.close()

    asyncio.run(run())
    assert len(requests) == 2
    for request, question in zip(requests, ["첫 질문", "다음 질문"], strict=True):
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["instructions"] == DEFAULT_INSTRUCTIONS
        assert payload["store"] is True
        assert payload["conversation"] == "conv_test"
        assert payload["input"] == [{"role": "user", "content": question}]
        assert payload["context_management"] == [
            {"type": "compaction", "compact_threshold": 20_000}
        ]
        assert "previous_response_id" not in payload
        assert "timeout_seconds" not in payload
    assert connection.is_closed


@pytest.mark.parametrize(
    ("history", "options", "expected_code"),
    [
        ([], {"conversaton_id": "conv_test"}, "AI_CONFIGURATION_ERROR"),
        ([], {"conversation_id": ""}, "AI_CONFIGURATION_ERROR"),
        ([], {"conversation_id": " \t"}, "AI_CONFIGURATION_ERROR"),
        ([], {"conversation_id": 123}, "AI_CONFIGURATION_ERROR"),
        ([], {"conversation_id": True}, "AI_CONFIGURATION_ERROR"),
        (
            [("이전", "답변")],
            {"conversation_id": "conv_test"},
            "AI_CONFIGURATION_ERROR",
        ),
        ([], {"timeout_seconds": True}, "AI_CONFIGURATION_ERROR"),
        ([], {"timeout_seconds": "30"}, "AI_CONFIGURATION_ERROR"),
        ([], {"timeout_seconds": None}, "AI_CONFIGURATION_ERROR"),
        ([], {"timeout_seconds": float("inf")}, "AI_CONFIGURATION_ERROR"),
        ([], {"timeout_seconds": float("nan")}, "AI_CONFIGURATION_ERROR"),
        ([], {"timeout_seconds": 0}, "AI_TIMEOUT"),
        ([], {"timeout_seconds": -1}, "AI_TIMEOUT"),
    ],
)
def test_invalid_request_options_fail_before_http(
    monkeypatch: pytest.MonkeyPatch,
    history: list[tuple[str, str]],
    options: dict[str, object],
    expected_code: str,
) -> None:
    """잘못된 옵션·중복 문맥·소진된 예산은 외부 호출 전에 거절한다."""
    requests: list[httpx2.Request] = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=_response())

    client, connection = _client(monkeypatch, respond)

    async def run() -> None:
        try:
            with pytest.raises(APIError) as caught:
                await client.generate_answer("질문", history, **options)
            assert caught.value.code == expected_code
        finally:
            await client.close()

    asyncio.run(run())
    assert requests == []
    assert connection.is_closed


@pytest.mark.parametrize(
    ("scenario", "expected_code", "expected_requests"),
    [
        ("429_recover", None, 2),
        ("429_exhaust", "AI_UNAVAILABLE", 5),
        ("429_no_retry", "AI_UNAVAILABLE", 1),
        ("408", "AI_UNAVAILABLE", 1),
        ("409", "AI_UNAVAILABLE", 1),
        ("500", "AI_UNAVAILABLE", 1),
        ("connection", "AI_UNAVAILABLE", 1),
        ("timeout", "AI_TIMEOUT", 1),
    ],
)
def test_conversation_retries_only_explicit_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_code: str | None,
    expected_requests: int,
) -> None:
    """결과가 불명확한 요청은 반복하지 않고 429만 동일 입력으로 재시도한다."""
    requests: list[httpx2.Request] = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if scenario == "429_recover" and len(requests) > 1:
            return httpx2.Response(200, json=_response())
        if scenario == "connection":
            raise httpx2.ConnectError("hidden connection", request=request)
        if scenario == "timeout":
            raise httpx2.ReadTimeout("hidden timeout", request=request)
        headers = {"Retry-After": "0.01"}
        if scenario == "429_no_retry":
            headers["x-should-retry"] = "false"
        status = 429 if scenario.startswith("429") else int(scenario)
        return httpx2.Response(
            status, headers=headers, json={"error": {"message": "hidden error"}}
        )

    sleep = AsyncMock()
    monkeypatch.setattr("app.clients.openai.asyncio.sleep", sleep)
    client, connection = _client(monkeypatch, respond)

    async def run() -> None:
        try:
            if expected_code is None:
                assert await client.generate_answer(
                    "질문", [], conversation_id="conv_test"
                ) == "답변"
            else:
                with pytest.raises(APIError) as caught:
                    await client.generate_answer(
                        "질문", [], conversation_id="conv_test"
                    )
                assert caught.value.code == expected_code
        finally:
            await client.close()

    asyncio.run(run())
    assert len(requests) == expected_requests
    assert sleep.await_count == expected_requests - 1
    payloads = [json.loads(request.content) for request in requests]
    assert all(payload == payloads[0] for payload in payloads)
    assert connection.is_closed


@pytest.mark.parametrize("scenario", ["call", "retry_budget"])
def test_remaining_timeout_limits_call_and_retry_wait(
    monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    """남은 제한 시간이 기본 제한보다 짧으면 호출·재시도 대기를 제한한다."""
    requests: list[httpx2.Request] = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if scenario == "call":
            await asyncio.sleep(0.2)
            return httpx2.Response(200, json=_response())
        return httpx2.Response(
            429,
            headers={"Retry-After": "1"},
            json={"error": {"message": "hidden error"}},
        )

    client, connection = _client(monkeypatch, respond)

    async def run() -> None:
        try:
            with pytest.raises(APIError) as caught:
                await client.generate_answer(
                    "질문", [], conversation_id="conv_test", timeout_seconds=0.03
                )
            assert caught.value.code == "AI_TIMEOUT"
        finally:
            await client.close()

    asyncio.run(run())
    assert len(requests) == 1
    assert connection.is_closed
