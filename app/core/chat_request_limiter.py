from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.errors import APIError


class ChatRequestLimiter:
    """단일 이벤트 루프에서 사용자별 동시 질문을 하나로 제한한다."""

    def __init__(self) -> None:
        """진행 중인 질문의 사용자 ID 집합을 준비한다."""
        self._active_users: set[int] = set()

    @asynccontextmanager
    async def acquire(self, user_id: int) -> AsyncIterator[None]:
        """사용자를 점유하고 질문 처리 종료 시 해제한다.

        Args:
            user_id: 인증된 사용자 ID.

        Yields:
            질문 처리 구간의 점유.

        Raises:
            APIError: 사용자의 다른 질문이 처리 중인 경우.
        """
        # 확인과 추가 사이에 await가 없어야 중복 점유를 막을 수 있다.
        if user_id in self._active_users:
            raise APIError("CHAT_BUSY")
        self._active_users.add(user_id)
        try:
            yield
        finally:
            self._active_users.remove(user_id)
