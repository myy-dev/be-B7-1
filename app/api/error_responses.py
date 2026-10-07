from typing import Any

from app.core.errors import APIError, AppError, internal_error
from app.schemas.error import ErrorResponse


def error_response(*errors: AppError) -> dict[str, Any]:
    """같은 HTTP 상태의 오류들을 공통 스키마와 개별 예시로 문서화한다.

    Args:
        errors: 서비스 또는 공통 핸들러에서 사용하는 오류 정의.

    Returns:
        FastAPI responses에 넣을 공통 모델·설명·OpenAPI examples.

    Raises:
        ValueError: 오류가 없거나 HTTP 상태가 서로 다른 경우.
    """
    if not errors or len({error.status_code for error in errors}) != 1:
        raise ValueError("하나 이상의 동일한 HTTP 상태 오류가 필요합니다.")
    examples = {
        error.code: {
            "summary": error.code,
            "value": ErrorResponse.model_validate(
                {
                    "error": {
                        "code": error.code,
                        "message": error.message,
                        "request_id": "16fd2706-8baf-433b-82eb-8c7fada847da",
                    }
                }
            ).model_dump(mode="json"),
        }
        for error in errors
    }
    return {
        "model": ErrorResponse,
        "description": " / ".join(error.message for error in errors),
        "content": {"application/json": {"examples": examples}},
    }


CHAT_NOT_FOUND_RESPONSE = error_response(APIError("CHAT_NOT_FOUND"))
INVALID_INPUT_RESPONSE = error_response(APIError("INVALID_INPUT"))
DB_ERROR_RESPONSE = error_response(APIError("DB_ERROR"), internal_error())
AI_UNAVAILABLE_RESPONSE = error_response(APIError("AI_UNAVAILABLE"))
AI_CONFIGURATION_ERROR_RESPONSE = error_response(APIError("AI_CONFIGURATION_ERROR"))
AI_TIMEOUT_RESPONSE = error_response(APIError("AI_TIMEOUT"))
