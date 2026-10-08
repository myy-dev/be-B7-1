from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from app.clients.ai import AIClient
from app.core.errors import APIError
from app.core.logging import log_event
from app.models.chat import ChatLog
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import (
    ChatDetailResponse,
    ChatListResponse,
    ChatResponse,
    MessageResponse,
)
from app.schemas.error import ResponseErrorCode


class ChatService:
    def __init__(self, repository: ChatRepository) -> None:
        self.repository = repository

    async def _save_failed_message(
        self,
        message: ChatLog,
        user_id: int,
        chat_id: UUID,
        error_code: ResponseErrorCode,
        started_at: float,
    ) -> None:
        """AI 처리 실패를 같은 대화 기록에 저장한다.

        Args:
            message: 실패로 전환할 대화 기록.
            user_id: 인증된 사용자 ID.
            chat_id: 질문을 보낸 채팅방 ID.
            error_code: 저장할 실패 코드.
            started_at: AI 호출 시작 시각의 성능 측정값.
        """
        log_event(
            "ai_call_failed",
            user_id=str(user_id),
            chat_id=chat_id,
            result="failure",
            error_code=error_code,
            duration_ms=round((perf_counter() - started_at) * 1000, 3),
        )
        message.status = "failed"
        message.error_code = error_code
        message.finished_at = datetime.now(UTC)
        await self.repository.save_message(message)
        log_event(
            "db_save_succeeded",
            user_id=str(user_id),
            chat_id=chat_id,
            result="success",
        )

    async def create_chat(self, user_id: int) -> ChatResponse:
        """사용자의 채팅방을 저장하고 생성 응답을 반환한다."""
        chat = await self.repository.create(user_id)
        log_event(
            "db_save_succeeded",
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

    async def delete_chat(self, chat_id: UUID, user_id: int) -> None:
        """본인 채팅방을 논리 삭제하고 대상이 없으면 조회 오류를 반환한다."""
        deleted = await self.repository.soft_delete(chat_id, user_id, datetime.now(UTC))
        if not deleted:
            raise APIError("CHAT_NOT_FOUND")
        log_event(
            "db_save_succeeded",
            user_id=str(user_id),
            chat_id=chat_id,
            result="success",
        )

    async def send_message(
        self,
        chat_id: UUID,
        user_id: int,
        request_id: UUID,
        question: str,
        ai_client: AIClient,
    ) -> MessageResponse:
        """질문을 먼저 저장하고 AI 답변 또는 실패 결과를 같은 기록에 저장한다.

        Args:
            chat_id: 질문을 보낼 채팅방의 ID.
            user_id: 인증된 사용자 ID.
            request_id: 서버에서 생성한 최초 질문 요청의 ID.
            question: 앞뒤 공백과 빈 입력 검증을 마친 질문.
            ai_client: 답변을 생성할 AI 클라이언트.

        Returns:
            질문·답변 저장을 완료한 대화 기록.

        Raises:
            APIError: 소유권 검사 또는 AI 호출에 실패한 경우.
            Exception: 예상하지 못한 AI 예외가 발생하고 실패 기록 저장 후 다시 전달되는 경우.
            SQLAlchemyError: 질문이나 처리 결과 저장에 실패한 경우.
        """
        chat = await self.repository.get_by_id_and_user(chat_id, user_id)
        if chat is None:
            raise APIError("CHAT_NOT_FOUND")
        previous = await self.repository.list_recent_completed(chat_id)
        history = [
            (item.question, item.answer) for item in previous if item.answer is not None
        ]
        message = ChatLog(
            request_id=request_id,
            chat_id=chat_id,
            question=question,
            model=ai_client.model,
            status="pending",
        )
        await self.repository.save_message(message)
        log_event(
            "db_save_succeeded",
            user_id=str(user_id),
            chat_id=chat_id,
            result="success",
        )
        started_at = perf_counter()
        log_event("ai_call_started", user_id=str(user_id), chat_id=chat_id)
        try:
            answer = await ai_client.generate_answer(question, history)
        except APIError as exc:
            await self._save_failed_message(
                message, user_id, chat_id, exc.api_code, started_at
            )
            raise
        except Exception:
            await self._save_failed_message(
                message, user_id, chat_id, "INTERNAL_ERROR", started_at
            )
            raise
        log_event(
            "ai_call_succeeded",
            user_id=str(user_id),
            chat_id=chat_id,
            result="success",
            duration_ms=round((perf_counter() - started_at) * 1000, 3),
        )
        message.answer = answer
        message.status = "completed"
        message.finished_at = datetime.now(UTC)
        await self.repository.save_message(message)
        log_event(
            "db_save_succeeded",
            user_id=str(user_id),
            chat_id=chat_id,
            result="success",
        )
        return MessageResponse.model_validate(message)
