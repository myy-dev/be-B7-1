from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.config import AuthSettings, get_auth_settings
from app.core.errors import AppError

password_hash = PasswordHash.recommended()
# 존재하지 않는 계정도 비밀번호 해시를 검증한다.
# 로그인 API 구현
_dummy_hash = password_hash.hash("dummy-password-for-login")


async def hash_password(password: str) -> str:
    return await run_in_threadpool(password_hash.hash, password)


# 로그인 API 구현
async def verify_password(password: str, hashed: str | None) -> bool:
    valid = await run_in_threadpool(
        password_hash.verify, password, hashed or _dummy_hash
    )
    return hashed is not None and valid


# 로그인 API 구현
def auth_settings() -> AuthSettings:
    try:
        return get_auth_settings()
    except ValidationError:
        raise AppError(
            "AUTH_CONFIGURATION_ERROR", "인증 서비스 설정을 확인해야 합니다.", 503
        ) from None


# 로그인 API 구현
def create_access_token(user_id: int) -> tuple[str, int]:
    settings = auth_settings()
    now = datetime.now(UTC)
    expires_in = settings.access_token_expire_minutes * 60
    token = jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    return token, expires_in


# 로그인 API 구현
def decode_access_token(token: str) -> int:
    settings = auth_settings()
    claims = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=["HS256"],
        options={"require": ["sub", "iat", "exp"]},
    )
    subject = claims["sub"]
    if not isinstance(subject, str) or not subject.isascii() or not subject.isdigit():
        raise jwt.InvalidTokenError("Invalid subject")
    user_id = int(subject)
    if user_id < 1 or user_id > 2**63 - 1:
        raise jwt.InvalidTokenError("Invalid subject")
    return user_id
