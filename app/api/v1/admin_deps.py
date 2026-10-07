from fastapi import Header

from app.api.dependencies import DBSession
from app.core.config import get_settings
from app.repositories.admin_db import (
    DbChatLogRepository,
    DbSessionRepository,
    DbUserRepository,
)
from app.repositories.admin_system_log import SystemLogFileRepository
from app.services.admin_service import AdminService


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    # 관리자 판정은 세션 쿠키가 아니라 Authorization 헤더(JWT)로 한다. 쿠키를 쓰지
    # 않으므로 쿠키가 위조돼도 관리자 권한이 바뀌지 않는다. 지금은 검사 없이 통과하는
    # 임시 구현이라 아직은 누구나 통과한다.
    # TODO(회원 담당): JWT·role이 정해지면 authorization을 검증해 관리자만 통과시킨다.
    return {"role": "admin", "mock": False}


def get_admin_service(db: DBSession) -> AdminService:
    # 회원·대화·세션은 실제 DB에서 읽는다. 시스템 로그만 파일 조회다.
    settings = get_settings()
    return AdminService(
        users=DbUserRepository(db),
        chat_logs=DbChatLogRepository(db),
        sessions=DbSessionRepository(db),
        system_logs=SystemLogFileRepository(settings.system_log_path),
    )
