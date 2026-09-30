from abc import ABC, abstractmethod
from datetime import datetime


class UserRepository(ABC):
    @abstractmethod
    async def list_users(self, page: int, size: int) -> tuple[list[dict], int]: ...

    @abstractmethod
    async def get_user(self, user_id: int) -> dict | None: ...


class ChatLogRepository(ABC):
    @abstractmethod
    async def list_logs(
        self,
        user_id: int | None,
        start: datetime | None,
        end: datetime | None,
        page: int,
        size: int,
    ) -> tuple[list[dict], int]: ...


class SessionRepository(ABC):
    @abstractmethod
    async def list_sessions(
        self, user_id: int, page: int, size: int
    ) -> tuple[list[dict], int]: ...

    @abstractmethod
    async def get_session(self, session_id: int) -> dict | None: ...


class SystemLogRepository(ABC):
    @abstractmethod
    async def query(
        self,
        level: str | None,
        event: str | None,
        start: datetime | None,
        end: datetime | None,
        page: int,
        size: int,
    ) -> tuple[list[dict], int]: ...
