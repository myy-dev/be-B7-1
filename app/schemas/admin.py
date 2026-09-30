from datetime import datetime

from pydantic import BaseModel


class UserSummary(BaseModel):
    id: int
    username: str
    name: str
    created_at: datetime


class UserDetail(UserSummary):
    last_login_at: datetime | None = None


class ChatLogItem(BaseModel):
    id: int
    user_id: int
    session_id: int | None
    question: str
    response: str
    created_at: datetime


class SessionItem(BaseModel):
    id: int
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
