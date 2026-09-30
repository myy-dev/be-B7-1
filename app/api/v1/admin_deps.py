import os

from fastapi import Header

from app.repositories.admin_mock import (
    MockChatLogRepository,
    MockSessionRepository,
    MockUserRepository,
)
from app.repositories.admin_system_log import SystemLogFileRepository
from app.services.admin_service import AdminService

SYSTEM_LOG_PATH = os.getenv("SYSTEM_LOG_PATH", "logs/system.jsonl")


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    return {"role": "admin", "mock": True}


def get_admin_service() -> AdminService:
    return AdminService(
        users=MockUserRepository(),
        chat_logs=MockChatLogRepository(),
        sessions=MockSessionRepository(),
        system_logs=SystemLogFileRepository(SYSTEM_LOG_PATH),
    )
