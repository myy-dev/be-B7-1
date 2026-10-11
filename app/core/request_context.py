from contextvars import ContextVar
from uuid import UUID

request_id_context: ContextVar[UUID | None] = ContextVar("request_id", default=None)
