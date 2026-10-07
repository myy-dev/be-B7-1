from typing import Literal

from pydantic import UUID4, BaseModel, Field

ErrorCode = Literal[
    "UNAUTHORIZED",
    "CHAT_NOT_FOUND",
    "CHAT_BUSY",
    "INVALID_INPUT",
    "DB_ERROR",
    "AI_UNAVAILABLE",
    "AI_CONFIGURATION_ERROR",
    "AI_TIMEOUT",
]

ResponseErrorCode = ErrorCode | Literal["INTERNAL_ERROR"]


class ErrorDetail(BaseModel):
    """오류 코드, 안내 문구와 현재 요청의 식별자를 표현한다."""

    code: ResponseErrorCode = Field(description="발생한 오류의 식별 코드")
    message: str = Field(description="사용자에게 표시할 오류 안내 문구")
    request_id: UUID4 = Field(
        description="오류가 발생한 요청의 UUID4. 응답의 X-Request-ID와 일치",
        examples=["16fd2706-8baf-433b-82eb-8c7fada847da"],
    )


class ErrorResponse(BaseModel):
    """인증·입력·처리 오류에 사용하는 공통 응답을 표현한다."""

    error: ErrorDetail
