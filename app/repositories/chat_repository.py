from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, insert, literal, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DatabaseSaveError
from app.models.chat import Chat, ChatLog


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_id: int) -> tuple[Chat, bool]:
        """빈 채팅방을 재사용하거나 새로 생성한다."""
        has_messages = exists().where(ChatLog.chat_id == Chat.chat_id)
        empty_chat_query = (
            select(Chat)
            .where(
                Chat.user_id == user_id,
                Chat.deleted_at.is_(None),
                ~has_messages,
            )
            .order_by(Chat.created_at.desc(), Chat.chat_id.desc())
            .limit(1)
        )
        stmt = (
            insert(Chat)
            .from_select(
                ["user_id"],
                select(literal(user_id)).where(~empty_chat_query.exists()),
            )
            .returning(Chat)
        )
        try:
            chat = await self.session.scalar(stmt)
            created = chat is not None
            if chat is None:
                result = await self.session.execute(empty_chat_query)
                chat = result.scalar_one()
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseSaveError(exc) from exc
        return chat, created

    async def list_by_user(self, user_id: int) -> list[Chat]:
        """사용자의 채팅방 목록을 조회한다."""
        result = await self.session.scalars(
            select(Chat)
            .where(Chat.user_id == user_id, Chat.deleted_at.is_(None))
            .order_by(Chat.created_at.desc(), Chat.chat_id.desc())
        )
        return list(result.all())

    async def get_conversation_id(self, chat_id: UUID) -> str | None:
        """채팅방에 저장된 현재 Conversation ID를 조회한다.

        Args:
            chat_id: 소유권 검사를 마친 채팅방의 ID.

        Returns:
            저장된 Conversation ID 또는 연결되지 않은 경우 None.
        """
        return await self.session.scalar(
            select(Chat.conversation_id).where(Chat.chat_id == chat_id)
        )

    async def save_conversation_id(self, chat_id: UUID, conversation_id: str) -> None:
        """채팅방의 Conversation ID를 저장한다.

        Args:
            chat_id: 소유권 검사를 마친 채팅방의 ID.
            conversation_id: OpenAI에서 생성한 Conversation ID.

        Raises:
            DatabaseSaveError: ID 저장에 실패한 경우.
        """
        try:
            await self.session.execute(
                update(Chat)
                .where(Chat.chat_id == chat_id)
                .values(conversation_id=conversation_id)
            )
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseSaveError(exc) from exc

    async def list_recent_completed(self, chat_id: UUID) -> list[ChatLog]:
        """채팅방의 최근 완료된 대화 기록을 조회한다.

        Args:
            chat_id: 소유권 검사를 마친 채팅방의 ID.

        Returns:
            생성 시각·요청 ID 오름차순으로 정렬한 완료 기록.
        """
        result = await self.session.scalars(
            select(ChatLog)
            .where(ChatLog.chat_id == chat_id, ChatLog.status == "completed")
            .order_by(ChatLog.created_at.desc(), ChatLog.request_id.desc())
            .limit(5)
        )
        return list(reversed(result.all()))

    async def save_message(self, message: ChatLog) -> ChatLog:
        """대화 기록을 저장하거나 갱신한다.

        Args:
            message: 저장할 질문 또는 갱신한 처리 결과.

        Returns:
            커밋을 마친 대화 기록.

        Raises:
            SQLAlchemyError: 저장 실패 시 롤백한 뒤 예외를 전달한다.
        """
        try:
            self.session.add(message)
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseSaveError(exc) from exc
        return message

    async def get_by_id_and_user(self, chat_id: UUID, user_id: int) -> Chat | None:
        """ID와 사용자로 채팅방을 조회한다."""
        return await self.session.scalar(
            select(Chat).where(
                Chat.chat_id == chat_id,
                Chat.user_id == user_id,
                Chat.deleted_at.is_(None),
            )
        )

    async def soft_delete(
        self, chat_id: UUID, user_id: int, deleted_at: datetime
    ) -> bool:
        """채팅방을 논리 삭제한다."""
        try:
            deleted_id = await self.session.scalar(
                update(Chat)
                .where(
                    Chat.chat_id == chat_id,
                    Chat.user_id == user_id,
                    Chat.deleted_at.is_(None),
                )
                .values(deleted_at=deleted_at)
                .returning(Chat.chat_id)
            )
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatabaseSaveError(exc) from exc
        return deleted_id is not None

    async def list_messages(self, chat_id: UUID) -> list[ChatLog]:
        """채팅방의 대화 기록을 조회한다."""
        result = await self.session.scalars(
            select(ChatLog)
            .where(ChatLog.chat_id == chat_id)
            .order_by(ChatLog.created_at.asc(), ChatLog.request_id.asc())
        )
        return list(result.all())
