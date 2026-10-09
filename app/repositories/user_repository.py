from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 회원 조회: 정규화된 아이디로 DB에서 회원 한 명을 찾는다.
    async def get_by_username(self, username: str) -> User | None:
        return await self.session.scalar(select(User).where(User.username == username))

    # 회원 저장: 일반 회원 권한으로 저장하고 DB 저장 실패 시 롤백한다.
    async def create(self, username: str, hashed_password: str, name: str) -> User:
        user = User(
            username=username, password_hash=hashed_password, name=name, role="user"
        )
        self.session.add(user)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return user

    # 로그인 API 구현: 마지막 로그인 시각을 UTC로 기록하고 DB에 저장한다.
    async def record_login(self, user: User) -> None:
        user.last_login_at = datetime.now(UTC)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
