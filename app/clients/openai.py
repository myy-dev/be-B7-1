import asyncio
import json
from math import isfinite
from random import uniform
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
)
from openai.types.responses import Response, ResponseInputParam

from app.clients.ai import DEFAULT_INSTRUCTIONS
from app.core.errors import APIError

COMPACT_THRESHOLD = 20_000


class OpenAIClient:
    """OpenAI SDK로 답변을 생성하고 호출 오류를 공통 오류로 변환한다."""

    def __init__(
        self, api_key: str, model: str, timeout: float, max_retries: int
    ) -> None:
        """AI 클라이언트를 초기화한다.

        Args:
            api_key: 서버의 OpenAI API 키.
            model: 답변을 생성할 모델 ID.
            timeout: 전체 AI 호출의 제한 시간(초).
            max_retries: 직접 재시도에 사용할 최대 횟수. 최초 호출은 제외한다.
        """
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=0)

    async def create_conversation(self) -> str:
        """OpenAI Conversation을 생성하고 ID를 반환한다.

        Returns:
            생성된 Conversation의 ID.

        Raises:
            APIError: 타임아웃, 서버 설정 오류 또는 Conversation 생성 실패.
        """
        try:
            async with asyncio.timeout(self.timeout):
                conversation = await self._client.conversations.create()
        except (APITimeoutError, TimeoutError) as exc:
            raise APIError("AI_TIMEOUT") from exc
        except (
            AuthenticationError,
            PermissionDeniedError,
            NotFoundError,
        ) as exc:
            raise APIError("AI_CONFIGURATION_ERROR") from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise APIError("AI_UNAVAILABLE") from exc
        except json.JSONDecodeError as exc:
            raise APIError("AI_UNAVAILABLE") from exc
        try:
            conversation_id = conversation.id
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise APIError("AI_UNAVAILABLE") from exc
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise APIError("AI_UNAVAILABLE")
        return conversation_id

    async def generate_answer(
        self,
        question: str,
        history: list[tuple[str, str]],
        **kwargs: Any,
    ) -> str:
        """Conversation 또는 대화 이력을 바탕으로 AI 답변을 생성한다.

        Args:
            question: 현재 사용자의 질문.
            history: 시간순으로 정렬한 이전 질문·답변 쌍.
            **kwargs: conversation_id와 남은 제한 시간인 timeout_seconds.

        Returns:
            완성된 텍스트 답변.

        Raises:
            APIError: 타임아웃, 서버 설정 오류 또는 유효한 답변 생성 실패.
        """
        if kwargs.keys() - {"conversation_id", "timeout_seconds"}:
            raise APIError("AI_CONFIGURATION_ERROR")
        conversation_id = kwargs.get("conversation_id")
        if conversation_id is not None and (
            not isinstance(conversation_id, str) or not conversation_id.strip()
        ):
            raise APIError("AI_CONFIGURATION_ERROR")
        if conversation_id is not None and history:
            raise APIError("AI_CONFIGURATION_ERROR")
        timeout = kwargs.get("timeout_seconds", self.timeout)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not isfinite(timeout)
        ):
            raise APIError("AI_CONFIGURATION_ERROR")
        if timeout <= 0:
            raise APIError("AI_TIMEOUT")
        messages: ResponseInputParam = []
        for previous_question, answer in history:
            messages.append({"role": "user", "content": previous_question})
            messages.append({"role": "assistant", "content": answer})
        messages.append({"role": "user", "content": question})
        try:
            response = await self._request_with_retries(
                messages,
                conversation_id=conversation_id,
                timeout=float(timeout),
            )
        except (APITimeoutError, TimeoutError) as exc:
            raise APIError("AI_TIMEOUT") from exc
        except (
            AuthenticationError,
            PermissionDeniedError,
            NotFoundError,
        ) as exc:
            raise APIError("AI_CONFIGURATION_ERROR") from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise APIError("AI_UNAVAILABLE") from exc
        except json.JSONDecodeError as exc:
            raise APIError("AI_UNAVAILABLE") from exc
        return self._extract_answer(response)

    async def _request_with_retries(
        self,
        messages: ResponseInputParam,
        *,
        conversation_id: str | None = None,
        timeout: float | None = None,
    ) -> Response:
        """재시도 정책에 따라 AI API를 호출한다."""
        loop = asyncio.get_running_loop()
        request_timeout = self.timeout if timeout is None else timeout
        deadline = loop.time() + request_timeout
        async with asyncio.timeout(request_timeout):
            for attempt in range(self.max_retries + 1):
                if loop.time() >= deadline:
                    raise TimeoutError
                try:
                    return await self._client.responses.create(
                        model=self.model,
                        instructions=DEFAULT_INSTRUCTIONS,
                        input=messages,
                        conversation=conversation_id,
                        context_management=(
                            [
                                {
                                    "type": "compaction",
                                    "compact_threshold": COMPACT_THRESHOLD,
                                }
                            ]
                            if conversation_id is not None
                            else None
                        ),
                        store=conversation_id is not None,
                    )
                except (APIConnectionError, APIStatusError) as exc:
                    if attempt == self.max_retries or not self._should_retry(
                        exc, conversation_id=conversation_id
                    ):
                        raise
                    delay = self._retry_delay(exc, attempt)
                    if delay >= deadline - loop.time():
                        raise TimeoutError from exc
                    await asyncio.sleep(delay)
        raise APIError("AI_UNAVAILABLE")

    def _extract_answer(self, response: Response) -> str:
        """AI 응답을 검증하고 답변을 추출한다."""
        try:
            response_status = response.status
            answer = response.output_text
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise APIError("AI_UNAVAILABLE") from exc
        if (
            response_status != "completed"
            or not isinstance(answer, str)
            or not answer.strip()
        ):
            raise APIError("AI_UNAVAILABLE")
        return answer

    def _should_retry(
        self,
        error: APIConnectionError | APIStatusError,
        *,
        conversation_id: str | None = None,
    ) -> bool:
        """요청 방식과 오류에 따라 재시도 여부를 판단한다."""
        if isinstance(error, APIStatusError):
            if error.response.headers.get("x-should-retry") == "false":
                return False
            if conversation_id is not None:
                return error.status_code == 429
            return error.status_code in {408, 409, 429} or (
                500 <= error.status_code < 600
            )
        return conversation_id is None

    def _retry_delay(
        self, error: APIConnectionError | APIStatusError, retry_index: int
    ) -> float:
        """재시도 대기 시간을 계산한다."""
        if isinstance(error, APIStatusError):
            try:
                delay = float(error.response.headers.get("retry-after", ""))
            except ValueError:
                pass
            else:
                if isfinite(delay) and delay > 0:
                    return delay
        base_delay = 8.0 if retry_index >= 3 else 1.0 * 2**retry_index
        return base_delay * uniform(0.75, 1.0)

    async def close(self) -> None:
        """AI 클라이언트의 연결 자원을 정리한다."""
        await self._client.close()
