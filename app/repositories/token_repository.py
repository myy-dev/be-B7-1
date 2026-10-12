from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.revoked_token import RevokedToken


class TokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 회원 인증: DB에 폐기 기록이 있으면 해당 토큰의 사용을 거절한다.
    async def is_revoked(self, token: str) -> bool:
        key = sha256(token.encode()).hexdigest()
        return await self.session.get(RevokedToken, key) is not None

    # 로그아웃 구현: 만료된 기록을 정리하고 현재 토큰을 중복 없이 폐기한다.
    async def revoke(self, token: str, expires_at: datetime) -> None:
        key = sha256(token.encode()).hexdigest()
        try:
            await self.session.execute(
                delete(RevokedToken).where(RevokedToken.expires_at <= datetime.now(UTC))
            )
            await self.session.execute(
                insert(RevokedToken)
                .values(token_hash=key, expires_at=expires_at)
                .on_conflict_do_nothing(index_elements=["token_hash"])
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
