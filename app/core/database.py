from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import ConnectionPoolEntry

from app.core.config import get_settings

DATABASE_URL = get_settings().database_url

engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(
    connection: DBAPIConnection, connection_record: ConnectionPoolEntry
) -> None:
    """각 SQLite 연결에서 채팅방·대화 기록 외래키 검사를 활성화한다."""
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


class Base(DeclarativeBase):
    pass


async def create_db_and_tables() -> None:
    # create_all 전에 모델을 등록한다. 라우터의 import 순서에 의존하지 않는다.
    from app.models import (
        revoked_token,  # noqa: F401
        user,  # noqa: F401
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
