from uuid import UUID

from app.core.errors import APIError
from app.core.logging import log_event
from app.repositories.chat import ChatRepository
from app.schemas.chat import (
    ChatDetailResponse,
    ChatListResponse,
    ChatResponse,
    MessageResponse,
)


class ChatService:
    def __init__(self, repository: ChatRepository) -> None:
        self.repository = repository

    async def create_chat(self, user_id: int) -> ChatResponse:
        """사용자의 채팅방을 저장하고 생성 응답을 반환한다."""
        chat = await self.repository.create(user_id)
        log_event(
            "db_saved",
            user_id=str(user_id),
            chat_id=chat.chat_id,
            result="success",
        )
        return ChatResponse.model_validate(chat)

    async def list_chats(self, user_id: int) -> ChatListResponse:
        """사용자에게 속한 전체 채팅방을 목록으로 내림차순으로 반환한다."""
        chats = await self.repository.list_by_user(user_id)
        return ChatListResponse(
            items=[ChatResponse.model_validate(chat) for chat in chats]
        )

    async def get_chat(self, chat_id: UUID, user_id: int) -> ChatDetailResponse:
        """소유권을 확인하고 채팅방과 전체 대화 기록을 반환한다."""
        chat = await self.repository.get_by_id_and_user(chat_id, user_id)
        if chat is None:
            raise APIError("CHAT_NOT_FOUND")
        messages = await self.repository.list_messages(chat_id)
        return ChatDetailResponse(
            chat_id=chat.chat_id,
            created_at=chat.created_at,
            messages=[MessageResponse.model_validate(message) for message in messages],
        )
