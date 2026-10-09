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
from app.repositories.token_repository import TokenRepository
from app.services.admin_service import AdminService


# 관리자 권한 검사: JWT 인증 후 DB의 회원 권한을 확인하고 일반 회원은 403으로 거절한다.
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
    # 로그아웃 구현: 관리자 API도 폐기된 액세스 토큰의 사용을 거절한다.
    if await TokenRepository(db).is_revoked(authorization[7:]):
        raise unauthorized
    role = await db.scalar(select(User.role).where(User.id == user_id))
    if role is None:
        raise unauthorized
    if role != "admin":
        raise forbidden
    # user_id는 역할 변경 API의 본인 강등 가드가 쓴다.
    return {"role": "admin", "mock": False, "user_id": user_id}


def get_admin_service(db: DBSession) -> AdminService:
    # 회원·대화·세션은 실제 DB에서 읽는다. 시스템 로그만 파일 조회다.
    settings = get_settings()
    return AdminService(
        users=DbUserRepository(db),
        chat_logs=DbChatLogRepository(db),
        sessions=DbSessionRepository(db),
        system_logs=SystemLogFileRepository(settings.system_log_path),
    )
