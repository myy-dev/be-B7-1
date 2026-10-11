"""관리자 조회 로직.

라우터는 이 서비스에만 의존하고, 서비스는 저장소 인터페이스에만 의존한다.
그래서 저장 방식을 임시에서 실제 DB로 바꿔도 이 파일은 그대로다. 조회 결과가
없으면 404(AppError)로 알린다.
"""

from datetime import datetime

from app.core.errors import AppError
from app.repositories.admin_repositories import (
    ChatLogRepository,
    SessionRepository,
    SystemLogRepository,
    UserRepository,
)


class AdminService:
    def __init__(
        self,
        users: UserRepository,
        chat_logs: ChatLogRepository,
        sessions: SessionRepository,
        system_logs: SystemLogRepository,
    ) -> None:
        self.users = users
        self.chat_logs = chat_logs
        self.sessions = sessions
        self.system_logs = system_logs

    async def list_users(self, page: int, size: int) -> tuple[list[dict], int]:
        return await self.users.list_users(page, size)

    async def get_user(self, user_id: int) -> dict:
        user = await self.users.get_user(user_id)
        if user is None:
            raise AppError(
                "USER_NOT_FOUND", "회원을 찾을 수 없습니다.", status_code=404
            )
        return user

    async def update_role(
        self, user_id: int, role: str, caller_id: int | None = None
    ) -> dict:
        if role not in ("admin", "user"):
            raise AppError(
                "INVALID_ROLE",
                "역할은 admin 또는 user만 지정할 수 있습니다.",
                422,
            )
        if caller_id is not None and user_id == caller_id and role != "admin":
            raise AppError(
                "CANNOT_DEMOTE_SELF",
                "자기 자신의 관리자 권한은 해제할 수 없습니다.",
                403,
            )
        updated = await self.users.update_role(user_id, role)
        if updated is None:
            raise AppError(
                "USER_NOT_FOUND", "회원을 찾을 수 없습니다.", status_code=404
            )
        return updated

    async def list_logs(
        self,
        user_id: int | None,
        start: datetime | None,
        end: datetime | None,
        page: int,
        size: int,
    ) -> tuple[list[dict], int]:
        return await self.chat_logs.list_logs(user_id, start, end, page, size)

    async def list_sessions(
        self, user_id: int, page: int, size: int
    ) -> tuple[list[dict], int]:
        return await self.sessions.list_sessions(user_id, page, size)

    async def get_session(self, chat_id: str) -> dict:
        session = await self.sessions.get_session(chat_id)
        if session is None:
            raise AppError(
                "SESSION_NOT_FOUND", "세션을 찾을 수 없습니다.", status_code=404
            )
        return session

    async def list_system_logs(
        self,
        level: str | None,
        event: str | None,
        start: datetime | None,
        end: datetime | None,
        page: int,
        size: int,
    ) -> tuple[list[dict], int]:
        return await self.system_logs.query(level, event, start, end, page, size)
