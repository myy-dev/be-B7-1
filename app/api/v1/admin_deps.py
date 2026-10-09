from typing import Annotated

import jwt
from fastapi import Header, HTTPException
from sqlalchemy import select

from app.api.dependencies import DBSession
from app.core.config import get_settings
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.admin_db import (
    DbChatLogRepository,
    DbSessionRepository,
    DbUserRepository,
)
from app.repositories.admin_system_log import SystemLogFileRepository
from app.services.admin_service import AdminService


async def require_admin(
    db: DBSession,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    # 관리자 판정은 세션 쿠키가 아니라 Authorization 헤더(JWT)로 한다. 쿠키를 쓰지
    # 않으므로 쿠키가 위조돼도 관리자 권한이 바뀌지 않는다.
    forbidden = HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    unauthorized = HTTPException(
        status_code=401,
        detail="로그인이 필요합니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization or not authorization.startswith("Bearer "):
        raise unauthorized
    try:
        user_id = decode_access_token(authorization[7:])
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized from None
    role = await db.scalar(select(User.role).where(User.id == user_id))
    if role is None:
        raise unauthorized
    if role != "admin":
        raise forbidden
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
