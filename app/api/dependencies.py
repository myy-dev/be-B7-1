"""여러 라우터에서 재사용하는 요청·DB 의존성을 정의한다."""

from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.ai import AIClient
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import APIError
from app.repositories.chat_repository import ChatRepository
from app.services.chat_service import ChatService


def get_request_id(request: Request) -> UUID:
    """미들웨어가 생성한 현재 요청의 식별자를 반환한다.

    Args:
        request: 현재 HTTP 요청.

    Returns:
        서버에서 생성한 UUID4 식별자.
    """
    return request.state.request_id


DBSession = Annotated[AsyncSession, Depends(get_db)]
RequestId = Annotated[UUID, Depends(get_request_id)]


async def get_current_user_id() -> int:
    """로그인 구현 전 테스트용 사용자 ID를 반환한다.

    Returns:
        DB에 존재해야 하는 테스트용 사용자 ID 1.
    """
    # TODO: 유저 담당자의 실제 인증 의존성으로 교체한다.
    return 1


CurrentUserId = Annotated[int, Depends(get_current_user_id)]


def get_chat_service(
    request: Request, user_id: CurrentUserId, db: DBSession
) -> ChatService:
    """채팅 서비스를 생성하고 인증된 ID를 요청 로그에 연결한다.

    Args:
        request: 현재 HTTP 요청.
        user_id: 인증 의존성에서 제공한 사용자 ID.
        db: 요청의 비동기 DB 세션.

    Returns:
        채팅방과 대화 기록을 처리할 서비스.
    """
    request.state.user_id = user_id
    return ChatService(ChatRepository(db))


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


async def get_ai_client(user_id: CurrentUserId) -> AsyncGenerator[AIClient, None]:
    """인증 후 AI 설정을 확인하고 요청이 끝나면 HTTP 연결을 정리한다.

    Args:
        user_id: 인증 검사를 마친 사용자 ID.

    Yields:
        자동 재시도하지 않는 요청별 AI 클라이언트.

    Raises:
        APIError: 서버의 AI 설정이 없거나 유효하지 않은 경우.
    """
    try:
        settings = get_settings()
    except ValidationError as exc:
        raise APIError("AI_CONFIGURATION_ERROR") from exc
    if not settings.openai_api_key.strip() or not settings.openai_model.strip():
        raise APIError("AI_CONFIGURATION_ERROR")
    client = AIClient(
        settings.openai_api_key, settings.openai_model, settings.ai_timeout_seconds
    )
    try:
        yield client
    finally:
        await client.close()


AIClientDep = Annotated[AIClient, Depends(get_ai_client)]
