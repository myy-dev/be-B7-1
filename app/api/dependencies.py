"""여러 라우터에서 재사용하는 요청·DB 의존성을 정의한다."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import APIError
from app.repositories.chat import ChatRepository
from app.services.chat import ChatService


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
    """인증 연동 전의 채팅 접근을 거절한다.

    Returns:
        인증 연동 후 제공할 정수 사용자 ID.

    Raises:
        APIError: 인증 계약이 미연동 상태이므로 UNAUTHORIZED를 반환한다.
    """
    # TODO: 유저 담당자의 인증 의존성에서 정수 ID를 받는다.
    raise APIError("UNAUTHORIZED")


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
