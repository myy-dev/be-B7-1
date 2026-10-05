"""채팅방과 대화 기록의 API 응답 스키마를 정의한다."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    UUID4,
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    StringConstraints,
    model_validator,
)

from app.core.datetimes import to_utc
from app.schemas.error import ErrorCode

UTCDateTime = Annotated[AwareDatetime, AfterValidator(to_utc)]
MessageStatus = Literal["pending", "completed", "failed"]


class MessageCreateRequest(BaseModel):
    """질문의 앞뒤 공백을 제거하고 비어 있지 않은 입력을 받는다."""

    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChatResponse(BaseModel):
    """채팅방 생성 응답과 목록의 채팅방 항목을 표현한다."""

    model_config = ConfigDict(from_attributes=True)

    chat_id: UUID
    created_at: UTCDateTime


class ChatListResponse(BaseModel):
    """사용자 소유의 전체 채팅방 목록을 표현한다."""

    items: list[ChatResponse]


class MessageResponse(BaseModel):
    """질문 한 개와 답변 최대 한 개로 구성된 대화 기록을 표현한다."""

    model_config = ConfigDict(from_attributes=True)

    request_id: UUID4
    chat_id: UUID
    question: str
    answer: str | None
    status: MessageStatus
    error_code: ErrorCode | None
    created_at: UTCDateTime
    finished_at: UTCDateTime | None

    @model_validator(mode="after")
    def validate_status_fields(self) -> Self:
        """처리 상태에 따른 답변·오류 코드·종료 시각의 조합을 검증한다.

        Returns:
            상태별 필드 규칙을 만족하는 대화 기록.

        Raises:
            ValueError: 필드 값이 처리 상태와 일치하지 않는 경우.
        """
        match self.status:
            case "pending":
                if any(
                    value is not None
                    for value in (self.answer, self.error_code, self.finished_at)
                ):
                    raise ValueError("처리 중인 기록의 결과 필드는 null이어야 합니다.")
            case "completed":
                if (
                    self.answer is None
                    or not self.answer.strip()
                    or self.error_code is not None
                    or self.finished_at is None
                ):
                    raise ValueError("완료 기록에는 답변과 종료 시각이 필요합니다.")
            case "failed":
                if (
                    self.answer is not None
                    or self.error_code is None
                    or self.finished_at is None
                ):
                    raise ValueError("실패 기록에는 오류 코드와 종료 시각이 필요합니다.")
        return self


class ChatDetailResponse(ChatResponse):
    """채팅방 정보와 처리 중·성공·실패를 포함한 전체 기록을 표현한다."""

    messages: list[MessageResponse]
