from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.core.logging import log_event
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, LoginResponse, SignupRequest


# 회원가입 오류: 중복 아이디에 대해 공통 형식의 409 오류를 만든다.
def username_taken() -> AppError:
    return AppError("USERNAME_TAKEN", "이미 사용 중인 아이디입니다.", status_code=409)


class AuthService:
    def __init__(self, users: UserRepository) -> None:
        self.users = users

    # 회원가입 처리: 중복 검사 후 비밀번호를 해시하고 저장하며 동시 중복도 처리한다.
    async def signup(self, data: SignupRequest) -> User:
        if await self.users.get_by_username(data.username) is not None:
            raise username_taken()
        hashed_password = await hash_password(data.password.get_secret_value())
        try:
            user = await self.users.create(data.username, hashed_password, data.name)
        except IntegrityError:
            # 사전 조회 후 다른 요청이 먼저 저장한 경우에도 같은 중복 오류를 준다.
            # 다른 무결성 오류를 아이디 중복으로 잘못 처리하지 않는다.
            if await self.users.get_by_username(data.username) is not None:
                raise username_taken() from None
            raise
        log_event("user_signed_up", user_id=str(user.id), result="success")
        return user

    # 로그인 API 구현: 회원 조회·비밀번호 검증 후 JWT를 발급하고 로그인 시각을 저장한다.
    async def login(self, data: LoginRequest) -> LoginResponse:
        user = await self.users.get_by_username(data.username)
        valid = await verify_password(
            data.password.get_secret_value(), user.password_hash if user else None
        )
        if not valid or user is None:
            log_event(
                "user_login_failed",
                user_id=str(user.id) if user else None,
                result="failure",
                error_code="INVALID_CREDENTIALS",
                http_status=401,
            )
            raise AppError(
                "INVALID_CREDENTIALS", "아이디 또는 비밀번호가 올바르지 않습니다.", 401
            )
        token, expires_in = create_access_token(user.id)
        await self.users.record_login(user)
        log_event("user_logged_in", user_id=str(user.id), result="success")
        return LoginResponse(access_token=token, expires_in=expires_in)
