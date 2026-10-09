from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from pwdlib import PasswordHash
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.config import AuthSettings, get_auth_settings
from app.core.errors import AppError

password_hash = PasswordHash.recommended()
# 존재하지 않는 계정도 비밀번호 해시를 검증한다.
# 로그인 API 구현: 없는 계정도 해시 검증을 수행하도록 비교용 해시를 준비한다.
_dummy_hash = password_hash.hash("dummy-password-for-login")


# 비밀번호 보호: Argon2 해시를 별도 스레드에서 계산해 원문 저장을 방지한다.
async def hash_password(password: str) -> str:
    return await run_in_threadpool(password_hash.hash, password)


# 로그인 API 구현: 입력 비밀번호와 저장된 해시를 비교하고 없는 계정은 실패 처리한다.
async def verify_password(password: str, hashed: str | None) -> bool:
    valid = await run_in_threadpool(
        password_hash.verify, password, hashed or _dummy_hash
    )
    return hashed is not None and valid


# 로그인 API 구현: JWT 설정을 읽고 잘못된 설정은 공통 503 오류로 변환한다.
def auth_settings() -> AuthSettings:
    try:
        return get_auth_settings()
    except ValidationError:
        raise AppError(
            "AUTH_CONFIGURATION_ERROR", "인증 서비스 설정을 확인해야 합니다.", 503
        ) from None


# 로그인 API 구현: 회원 ID·발급 시각·만료 시각을 담은 HS256 JWT를 발급한다.
def create_access_token(user_id: int) -> tuple[str, int]:
    settings = auth_settings()
    now = datetime.now(UTC)
    expires_in = settings.access_token_expire_minutes * 60
    token = jwt.encode(
        {
            "sub": str(user_id),
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    return token, expires_in


# 로그인 API 구현: JWT 서명·만료·필수 클레임을 검증하고 유효한 회원 ID를 꺼낸다.
def decode_access_token_claims(token: str) -> dict:
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
    return claims


# 회원 인증: 검증된 JWT에서 현재 회원 ID를 반환한다.
def decode_access_token(token: str) -> int:
    return int(decode_access_token_claims(token)["sub"])
