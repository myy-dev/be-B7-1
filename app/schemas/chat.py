from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    UUID4,
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.datetimes import to_utc
from app.schemas.error import ErrorCode

UTCDateTime = Annotated[AwareDatetime, AfterValidator(to_utc)]
MessageStatus = Literal["pending", "completed", "failed"]


class MessageCreateRequest(BaseModel):
    question: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
        ),
        Field(
            description="AI에게 전달할 질문. 앞뒤 공백 제거 후 최소 1자",
            examples=["FastAPI가 뭐야?"],
        ),
    ]


class ChatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chat_id: UUID = Field(
        description="채팅방 식별자",
        examples=["e6100748-b7f0-48e6-a264-7c20a748cf93"],
    )
    created_at: UTCDateTime = Field(
        description="채팅방 생성 시각(UTC)",
        examples=["2026-10-02T03:00:00Z"],
    )


class ChatListResponse(BaseModel):
    items: list[ChatResponse] = Field(
        description="현재 사용자 소유의 전체 채팅방 목록. 없으면 빈 배열",
    )


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: UUID4 = Field(
        description="최초 질문 요청 및 대화 기록 식별자",
        examples=["16fd2706-8baf-433b-82eb-8c7fada847da"],
    )
    chat_id: UUID = Field(
        description="대화 기록이 속한 채팅방 식별자",
        examples=["e6100748-b7f0-48e6-a264-7c20a748cf93"],
    )
    question: str = Field(
        description="앞뒤 공백이 제거된 질문",
        examples=["FastAPI가 뭐야?"],
    )
    answer: str | None = Field(
        description="AI 답변. 처리 중이거나 실패한 경우 null",
        examples=["Python으로 웹 API를 만드는 프레임워크입니다."],
    )
    status: MessageStatus = Field(
        description="메시지 처리 상태",
        examples=["completed"],
    )
    error_code: ErrorCode | None = Field(
        description="처리 실패 시 오류 코드. 실패 상태가 아니면 null",
        examples=[None],
    )
    created_at: UTCDateTime = Field(
        description="질문 기록 생성 시각(UTC)",
        examples=["2026-10-02T03:00:05Z"],
    )
    finished_at: UTCDateTime | None = Field(
        description="처리가 완료되거나 실패한 시각. 처리 중이면 null",
        examples=["2026-10-02T03:00:07Z"],
    )

    @model_validator(mode="after")
    def validate_status_fields(self) -> Self:
        """처리 상태에 따른 결과 필드의 조합을 검증한다."""
        match self.status:
            case "pending":
                if any(
                    value is not None
                    for value in (
                        self.answer,
                        self.error_code,
                        self.finished_at,
                    )
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
                    raise ValueError(
                        "실패 기록에는 오류 코드와 종료 시각이 필요합니다."
                    )

        return self


class ChatDetailResponse(ChatResponse):
    messages: list[MessageResponse] = Field(
        description="처리 중·성공·실패를 포함한 전체 대화 기록. 없으면 빈 배열",
    )
