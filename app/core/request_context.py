"""현재 HTTP 요청의 서버 생성 식별자를 보관한다."""

from contextvars import ContextVar
from uuid import UUID

request_id_context: ContextVar[UUID | None] = ContextVar("request_id", default=None)
