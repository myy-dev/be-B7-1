"""API 공통 오류 응답 스키마를 정의한다."""

from typing import Literal

from pydantic import UUID4, BaseModel

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


class ErrorDetail(BaseModel):
    """오류 코드, 안내 문구와 현재 요청의 식별자를 표현한다."""

    code: ErrorCode
    message: str
    request_id: UUID4


class ErrorResponse(BaseModel):
    """인증·입력·처리 오류에 사용하는 공통 응답을 표현한다."""

    error: ErrorDetail
