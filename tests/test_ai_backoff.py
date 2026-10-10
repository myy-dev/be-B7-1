import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from openai import APIStatusError, AsyncOpenAI

from app.clients.openai import OpenAIClient
from app.core.errors import APIError


@pytest.mark.parametrize("failure", ["500", "connection", "timeout"])
@pytest.mark.parametrize("failures", [1, 4, 5])
def test_direct_retries_recover_or_exhaust(
    monkeypatch: pytest.MonkeyPatch, failure: str, failures: int
) -> None:
    """실제 SDK를 연결해 복구·최대 5회 호출·대기 순서와 동일 입력을 검증한다."""
    requests: list[httpx2.Request] = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if len(requests) <= failures:
            if failure == "connection":
                raise httpx2.ConnectError("test connection", request=request)
            if failure == "timeout":
                raise httpx2.ReadTimeout("test timeout", request=request)
            return httpx2.Response(500, json={"error": {"message": "test error"}})
        return httpx2.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 1,
            "status": "completed", "model": "test-model",
            "output": [{
                "id": "msg_test", "type": "message", "role": "assistant",
                "status": "completed",
                "content": [{
                    "type": "output_text", "text": "답변", "annotations": [],
                }],
            }],
        })

    connection = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    sdk = AsyncOpenAI(api_key="test-only", max_retries=0, http_client=connection)
    monkeypatch.setattr("app.clients.openai.AsyncOpenAI", MagicMock(return_value=sdk))
    jitter = MagicMock(side_effect=[0.75, 0.8, 0.9, 1.0])
    monkeypatch.setattr("app.clients.openai.uniform", jitter)
    sleep = AsyncMock()
    monkeypatch.setattr("app.clients.openai.asyncio.sleep", sleep)
    client = OpenAIClient("test-only", "test-model", 30, max_retries=4)

    async def run() -> None:
        try:
            if failures < 5:
                assert await client.generate_answer("질문", [("이전", "답변")]) == "답변"
            else:
                with pytest.raises(APIError) as caught:
                    await client.generate_answer("질문", [("이전", "답변")])
                expected = "AI_TIMEOUT" if failure == "timeout" else "AI_UNAVAILABLE"
                assert caught.value.code == expected
        finally:
            await client.close()

    asyncio.run(run())
    assert len(requests) == min(failures + 1, 5)
    assert [call.args[0] for call in sleep.await_args_list] == (
        [0.75, 1.6, 3.6, 8.0][:min(failures, 4)]
    )
    assert jitter.call_count == min(failures, 4)
    assert all(call.args == (0.75, 1.0) for call in jitter.call_args_list)
    payloads = [json.loads(request.content) for request in requests]
    assert all(payload == payloads[0] for payload in payloads)
    assert payloads[0]["input"] == [
        {"role": "user", "content": "이전"},
        {"role": "assistant", "content": "답변"},
        {"role": "user", "content": "질문"},
    ]
    assert connection.is_closed


@pytest.mark.parametrize(
    ("headers", "retry_index", "expected"),
    [
        ({"retry-after-ms": "1500", "Retry-After": "7"}, 0, 7.0),
        ({"retry-after-ms": "1500"}, 0, 0.75),
        ({"Retry-After": "7"}, 0, 7.0),
        ({"Retry-After": "1.5"}, 0, 1.5),
        ({"Retry-After": "Fri, 09 Oct 2026 12:00:05 GMT"}, 0, 0.75),
        ({"Retry-After": "invalid"}, 0, 0.75),
        ({"Retry-After": "nan"}, 0, 0.75),
        ({"Retry-After": "inf"}, 0, 0.75),
        ({"Retry-After": "0"}, 0, 0.75),
        ({"Retry-After": "-1"}, 0, 0.75),
        ({}, 4, 6.0),
        ({}, 10000, 6.0),
    ],
)
def test_server_delay_and_backoff_cap(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    retry_index: int,
    expected: float,
) -> None:
    """서버 초 값은 그대로 사용하고 그 외에는 백오프와 지터를 적용한다."""
    monkeypatch.setattr("app.clients.openai.AsyncOpenAI", MagicMock())
    monkeypatch.setattr("app.clients.openai.uniform", lambda low, high: 0.75)
    response = httpx2.Response(
        500, headers=headers, request=httpx2.Request("POST", "https://test/responses")
    )
    error = APIStatusError("test", response=response, body=None)
    client = OpenAIClient("test-only", "test-model", 30, max_retries=4)
    assert client._retry_delay(error, retry_index) == expected


@pytest.mark.parametrize(
    ("status", "headers", "expected"),
    [
        (408, {}, True), (409, {}, True), (429, {}, True),
        (500, {}, True), (599, {}, True),
        (400, {}, False), (401, {}, False), (403, {}, False),
        (404, {}, False), (422, {}, False), (600, {}, False),
        (500, {"x-should-retry": "false"}, False),
        (400, {"x-should-retry": "true"}, False),
    ],
)
def test_retry_classification(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    headers: dict[str, str],
    expected: bool,
) -> None:
    """허용된 상태만 재시도하고 서버의 재시도 금지 지시를 우선한다."""
    monkeypatch.setattr("app.clients.openai.AsyncOpenAI", MagicMock())
    response = httpx2.Response(
        status, headers=headers, request=httpx2.Request("POST", "https://test")
    )
    client = OpenAIClient("test-only", "test-model", 30, max_retries=4)
    assert client._should_retry(
        APIStatusError("test", response=response, body=None)
    ) is expected


@pytest.mark.parametrize("scenario", ["no_budget", "call", "wait", "cancel"])
def test_total_timeout_and_cancellation(
    monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    """대기 예산 부족·호출/대기 중 시간 초과·작업 취소 후 추가 호출을 막는다."""
    real_sleep = asyncio.sleep

    async def respond(**kwargs: object) -> object:
        if scenario == "call":
            await real_sleep(0.05)
        response = httpx2.Response(
            500, headers={"Retry-After": "0.001"},
            request=httpx2.Request("POST", "https://test"),
        )
        raise APIStatusError("test", response=response, body=None)

    async def wait(delay: float) -> None:
        if scenario == "cancel":
            raise asyncio.CancelledError
        await real_sleep(0.05)

    create = AsyncMock(side_effect=respond)
    sdk = SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr("app.clients.openai.AsyncOpenAI", MagicMock(return_value=sdk))
    sleep = AsyncMock(side_effect=wait)
    monkeypatch.setattr("app.clients.openai.asyncio.sleep", sleep)
    client = OpenAIClient("test-only", "test-model", 0.01, max_retries=4)
    if scenario == "no_budget":
        monkeypatch.setattr(client, "_retry_delay", lambda error, index: 30.0)

    async def run() -> None:
        if scenario == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await client.generate_answer("질문", [])
        else:
            with pytest.raises(APIError) as caught:
                await client.generate_answer("질문", [])
            assert caught.value.code == "AI_TIMEOUT"

    asyncio.run(run())
    assert create.await_count == 1
    assert sleep.await_count == (1 if scenario in {"wait", "cancel"} else 0)
