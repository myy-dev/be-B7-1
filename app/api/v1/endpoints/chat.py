from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.dependencies import AIClientDep, ChatServiceDep, CurrentUserId, RequestId
from app.api.error_responses import (
    AI_CONFIGURATION_ERROR_RESPONSE,
    AI_TIMEOUT_RESPONSE,
    AI_UNAVAILABLE_RESPONSE,
    CHAT_NOT_FOUND_RESPONSE,
    DB_ERROR_RESPONSE,
    INVALID_INPUT_RESPONSE,
    error_response,
)
from app.core.errors import APIError
from app.schemas.chat import (
    ChatDetailResponse,
    ChatListResponse,
    ChatResponse,
    MessageCreateRequest,
    MessageResponse,
)

# 로그인 API 구현
router = APIRouter(
    prefix="/chats",
    tags=["chats"],
    responses={401: error_response(APIError("UNAUTHORIZED"))},
)


@router.post(
    "",
    response_model=ChatResponse,
    status_code=status.HTTP_201_CREATED,
    summary="채팅방 생성",
    description=(
        "현재 사용자 소유의 새 채팅방을 생성합니다.\n\n"
        "**테스트:** 인증 구현 전까지 사용자 ID `1`로 처리합니다."
    ),
    responses={
        500: DB_ERROR_RESPONSE,
    },
)
async def create_chat(
    request: Request,
    user_id: CurrentUserId,
    service: ChatServiceDep,
) -> ChatResponse:
    response = await service.create_chat(user_id)
    request.state.chat_id = response.chat_id
    return response


@router.get(
    "",
    response_model=ChatListResponse,
    summary="내 채팅방 목록 조회",
    description=(
        "현재 사용자의 전체 채팅방을 생성 시각 내림차순으로 반환합니다. "
        "시각이 같으면 chat_id 내림차순으로 정렬합니다.\n\n"
        "**테스트:** 사용자 ID `1`의 채팅방을 조회합니다."
    ),
    responses={
        500: DB_ERROR_RESPONSE,
    },
)
async def list_chats(
    user_id: CurrentUserId,
    service: ChatServiceDep,
) -> ChatListResponse:
    return await service.list_chats(user_id)


@router.get(
    "/{chat_id}",
    response_model=ChatDetailResponse,
    summary="채팅방 상세 및 대화 기록 조회",
    description=(
        "채팅방 정보와 전체 대화 기록을 오래된 순으로 반환합니다.\n\n"
        "**테스트:** 사용자 ID `1`의 채팅방을 조회합니다."
    ),
    responses={
        404: CHAT_NOT_FOUND_RESPONSE,
        422: INVALID_INPUT_RESPONSE,
        500: DB_ERROR_RESPONSE,
    },
)
async def get_chat(
    chat_id: UUID,
    request: Request,
    user_id: CurrentUserId,
    service: ChatServiceDep,
) -> ChatDetailResponse:
    request.state.chat_id = chat_id
    return await service.get_chat(chat_id, user_id)


@router.post(
    "/{chat_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="질문 전송 및 AI 답변 받기",
    description=(
        "질문을 전송하고 AI 답변을 생성하여 저장합니다. "
        "최근 성공 대화 최대 5개를 문맥으로 사용합니다.\n\n"
        "**테스트:** 사용자 ID `1`로 실제 AI 호출과 DB 저장을 수행합니다."
    ),
    responses={
        404: CHAT_NOT_FOUND_RESPONSE,
        422: INVALID_INPUT_RESPONSE,
        500: DB_ERROR_RESPONSE,
        502: AI_UNAVAILABLE_RESPONSE,
        503: AI_CONFIGURATION_ERROR_RESPONSE,
        504: AI_TIMEOUT_RESPONSE,
    },
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
    request.state.chat_id = chat_id
    return await service.send_message(
        chat_id,
        user_id,
        request_id,
        body.question,
        ai_client,
    )
