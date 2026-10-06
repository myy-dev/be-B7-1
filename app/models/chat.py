from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.datetimes import UTCDateTimeType


class Chat(Base):
    """인증된 사용자 한 명이 소유하는 UUID 채팅방을 저장한다."""

    __tablename__ = "chats"
    __table_args__ = (
        Index("ix_chats_user_created_id", "user_id", "created_at", "chat_id"),
    )

    chat_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    # TODO: 회원 담당 PR 병합 후 기존 User 모델의 users.id 외래키를 연결한다.
    user_id: Mapped[int] = mapped_column(Integer(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTimeType(), nullable=False, default=func.now()
    )


class ChatLog(Base):
    """최초 질문의 요청 ID로 질문과 처리 결과를 한 행에 저장한다."""

    __tablename__ = "chat_logs"
    __table_args__ = (
        Index(
            "ix_chat_logs_chat_created_request", "chat_id", "created_at", "request_id"
        ),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_chat_logs_status",
        ),
        CheckConstraint(
            "(status = 'pending' AND answer IS NULL AND error_code IS NULL "
            "AND finished_at IS NULL) OR "
            "(status = 'completed' AND answer IS NOT NULL AND error_code IS NULL "
            "AND finished_at IS NOT NULL) OR "
            "(status = 'failed' AND answer IS NULL AND error_code IS NOT NULL "
            "AND finished_at IS NOT NULL)",
            name="ck_chat_logs_status_fields",
        ),
    )

    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    chat_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chats.chat_id"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTimeType(), nullable=False, default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        UTCDateTimeType(), nullable=True
    )
