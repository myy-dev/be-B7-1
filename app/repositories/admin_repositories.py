"""관리자 조회가 기대하는 저장소 규약.

서비스는 이 인터페이스에만 의존한다. 회원·대화·세션은 담당 스키마가 정해지면
실제 DB 구현으로, 시스템 로그는 파일 조회로 채운다. 교체해도 서비스·라우터는
그대로다. 조회 메서드는 (자른 목록, 전체 수)를 돌려준다.
"""

from abc import ABC, abstractmethod
from datetime import datetime


class UserRepository(ABC):
    """회원 담당 스키마에 의존한다."""

    @abstractmethod
    async def list_users(self, page: int, size: int) -> tuple[list[dict], int]: ...

    @abstractmethod
    async def get_user(self, user_id: int) -> dict | None: ...


class ChatLogRepository(ABC):
    """채팅 담당 스키마에 의존한다."""

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
    """채팅 담당 스키마에 의존한다. 세션 생성·삭제는 채팅 쪽, 여기서는 읽기만."""

    @abstractmethod
    async def list_sessions(
        self, user_id: int, page: int, size: int
    ) -> tuple[list[dict], int]: ...

    @abstractmethod
    async def get_session(self, chat_id: str) -> dict | None: ...


class SystemLogRepository(ABC):
    """JSONL 시스템 로그 조회. 기록 형식은 docs/system-logs.md를 따른다."""

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
