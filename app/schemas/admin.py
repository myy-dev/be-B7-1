"""관리자 조회 응답 형식.

프론트가 받는 JSON 모양이다. 여기 선언한 필드만 나가므로, 회원 스키마에
비밀번호 같은 필드가 있어도 응답에는 싣지 않는다.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class RoleUpdateRequest(BaseModel):
    role: str = Field(min_length=1, max_length=20)


class RoleUpdateResponse(BaseModel):
    id: int
    username: str
    role: str


class UserSummary(BaseModel):
    id: int
    username: str
    name: str
    role: str
    created_at: datetime


class UserDetail(UserSummary):
    last_login_at: datetime | None = None


class ChatLogItem(BaseModel):
    request_id: str
    chat_id: str
    question: str
    answer: str | None
    status: str
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


class SessionItem(BaseModel):
    chat_id: str
    user_id: int
    title: str
    created_at: datetime
    message_count: int


class SessionDetail(SessionItem):
    messages: list[ChatLogItem]


class SystemLogItem(BaseModel):
    timestamp: datetime
    level: str
    event: str
    request_id: str | None = None
    user_id: int | None = None
