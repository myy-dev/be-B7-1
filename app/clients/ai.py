import asyncio
import json

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
)
from openai.types.responses import ResponseInputParam

from app.core.errors import APIError


class AIClient:
    """자동 재시도 없이 비동기 Responses API를 호출한다."""

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        """요청에 사용할 설정과 SDK 클라이언트를 보관한다.

        Args:
            api_key: 서버의 OpenAI API 키.
            model: 답변을 생성할 모델 ID.
            timeout: 전체 AI 호출의 제한 시간(초).
        """
        self.model = model
        self.timeout = timeout
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=0)

    async def generate_answer(
        self, question: str, history: list[tuple[str, str]]
    ) -> str:
        """대화 문맥과 현재 질문을 보내고 완성된 답변만 반환한다.

        Args:
            question: 현재 사용자의 질문.
            history: 시간순으로 정렬한 이전 질문·답변 쌍.

        Returns:
            완성된 텍스트 답변.

        Raises:
            APIError: 타임아웃, 서버 설정 오류 또는 유효한 답변 생성 실패.
        """
        messages: ResponseInputParam = []
        for previous_question, answer in history:
            messages.append({"role": "user", "content": previous_question})
            messages.append({"role": "assistant", "content": answer})
        messages.append({"role": "user", "content": question})
        try:
            async with asyncio.timeout(self.timeout):
                response = await self._client.responses.create(
                    model=self.model, input=messages, store=False
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

    async def close(self) -> None:
        """앱이 종료되면 SDK의 비동기 HTTP 연결을 정리한다."""
        await self._client.close()
