from fastapi import Header

from app.core.config import get_settings
from app.repositories.admin_mock import (
    MockChatLogRepository,
    MockSessionRepository,
    MockUserRepository,
)
from app.repositories.admin_system_log import SystemLogFileRepository
from app.services.admin_service import AdminService


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    # TODO(회원 담당): JWT·role이 정해지면 authorization을 검증해 관리자만 통과시킨다.
    return {"role": "admin", "mock": True}


def get_admin_service() -> AdminService:
    # TODO(회원·채팅 담당): 스키마가 나오면 Mock 저장소를 실제 구현으로 바꾼다.
    settings = get_settings()
    return AdminService(
        users=MockUserRepository(),
        chat_logs=MockChatLogRepository(),
        sessions=MockSessionRepository(),
        system_logs=SystemLogFileRepository(settings.system_log_path),
    )
