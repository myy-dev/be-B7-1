from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.dependencies import AIClientDep, ChatServiceDep, CurrentUserId, RequestId
from app.schemas.chat import (
    ChatDetailResponse,
    ChatListResponse,
    ChatResponse,
    MessageCreateRequest,
    MessageResponse,
)

router = APIRouter(prefix="/api/v1/chats", tags=["chats"])


@router.post("", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    request: Request, user_id: CurrentUserId, service: ChatServiceDep
) -> ChatResponse:
    """현재 사용자의 채팅방을 생성한다.

    Args:
        request: 현재 HTTP 요청.
        user_id: 인증 의존성에서 제공한 사용자 ID.
        service: 채팅방을 처리할 서비스.

    Returns:
        생성한 채팅방의 정보.
    """
    response = await service.create_chat(user_id)
    request.state.chat_id = response.chat_id
    return response


@router.get("", response_model=ChatListResponse, status_code=status.HTTP_200_OK)
async def list_chats(
    user_id: CurrentUserId, service: ChatServiceDep
) -> ChatListResponse:
    """현재 사용자의 전체 채팅방을 조회한다.

    Args:
        user_id: 인증 의존성에서 제공한 사용자 ID.
        service: 채팅방을 처리할 서비스.

    Returns:
        생성 시각·ID 내림차순으로 정렬한 채팅방 목록.
    """
    return await service.list_chats(user_id)


@router.get(
    "/{chat_id}", response_model=ChatDetailResponse, status_code=status.HTTP_200_OK
)
async def get_chat(
    chat_id: UUID, request: Request, user_id: CurrentUserId, service: ChatServiceDep
) -> ChatDetailResponse:
    """소유권을 확인하고 채팅방과 전체 대화 기록을 조회한다.

    Args:
        chat_id: 조회할 채팅방의 UUID.
        request: 현재 HTTP 요청.
        user_id: 인증 의존성에서 제공한 사용자 ID.
        service: 채팅방을 처리할 서비스.

    Returns:
        채팅방 정보와 전체 대화 기록.
    """
    request.state.chat_id = chat_id
    return await service.get_chat(chat_id, user_id)


@router.post(
    "/{chat_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    chat_id: UUID,
    body: MessageCreateRequest,
    request: Request,
    user_id: CurrentUserId,
    request_id: RequestId,
    service: ChatServiceDep,
    ai_client: AIClientDep,
) -> MessageResponse:
    """현재 사용자의 질문을 보내고 저장을 마친 AI 답변을 반환한다.

    Args:
        chat_id: 질문을 보낼 채팅방의 UUID.
        body: 검증을 마친 질문 본문.
        request: 현재 HTTP 요청.
        user_id: 인증된 사용자 ID.
        request_id: 서버에서 생성한 질문 요청의 UUID4.
        service: 질문과 답변 저장을 처리할 서비스.
        ai_client: 답변을 생성할 AI 클라이언트.

    Returns:
        저장을 마친 질문·답변 한 건.
    """
    request.state.chat_id = chat_id
    return await service.send_message(
        chat_id, user_id, request_id, body.question, ai_client
    )
