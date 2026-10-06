from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_username(self, username: str) -> User | None:
        return await self.session.scalar(select(User).where(User.username == username))

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
