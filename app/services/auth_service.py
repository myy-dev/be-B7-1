from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.core.security import hash_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import SignupRequest


def username_taken() -> AppError:
    return AppError("USERNAME_TAKEN", "이미 사용 중인 아이디입니다.", status_code=409)


class AuthService:
    def __init__(self, users: UserRepository) -> None:
        self.users = users

    async def signup(self, data: SignupRequest) -> User:
        if await self.users.get_by_username(data.username) is not None:
            raise username_taken()
        hashed_password = await hash_password(data.password.get_secret_value())
        try:
            return await self.users.create(data.username, hashed_password, data.name)
        except IntegrityError:
            # 사전 조회 후 다른 요청이 먼저 저장한 경우에도 같은 중복 오류를 준다.
            # 다른 무결성 오류를 아이디 중복으로 잘못 처리하지 않는다.
            if await self.users.get_by_username(data.username) is not None:
                raise username_taken() from None
            raise
