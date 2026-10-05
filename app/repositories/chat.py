from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, ChatLog


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_id: int) -> Chat:
        """채팅방을 저장하고 커밋 완료 후 반환한다."""
        chat = Chat(user_id=user_id)
        try:
            self.session.add(chat)
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        return chat

    async def list_by_user(self, user_id: int) -> list[Chat]:
        """소유자의 전체 채팅방을 생성 시각·ID 내림차순으로 조회한다."""
        result = await self.session.scalars(
            select(Chat)
            .where(Chat.user_id == user_id)
            .order_by(Chat.created_at.desc(), Chat.chat_id.desc())
        )
        return list(result.all())

    async def get_by_id_and_user(self, chat_id: UUID, user_id: int) -> Chat | None:
        """ID와 소유자가 모두 일치하는 채팅방을 조회한다."""
        return await self.session.scalar(
            select(Chat).where(Chat.chat_id == chat_id, Chat.user_id == user_id)
        )

    async def list_messages(self, chat_id: UUID) -> list[ChatLog]:
        """채팅방의 전체 기록을 생성 시각·요청 ID 오름차순으로 조회한다."""
        result = await self.session.scalars(
            select(ChatLog)
            .where(ChatLog.chat_id == chat_id)
            .order_by(ChatLog.created_at.asc(), ChatLog.request_id.asc())
        )
        return list(result.all())
