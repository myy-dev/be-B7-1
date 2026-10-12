from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.errors import APIError


class ChatRequestLimiter:
    """단일 이벤트 루프에서 사용자별·전체 동시 질문 수를 제한한다."""

    def __init__(self, max_concurrent_requests: int) -> None:
        """전체 질문 한도와 진행 중인 사용자 집합을 준비한다.

        Args:
            max_concurrent_requests: 동시에 처리할 전체 질문 수의 상한.

        Raises:
            ValueError: 전체 질문 한도가 양수가 아닌 경우.
        """
        if max_concurrent_requests <= 0:
            raise ValueError("최대 동시 질문 수는 양수여야 합니다.")
        self._max_concurrent_requests = max_concurrent_requests
        self._active_users: set[int] = set()

    @asynccontextmanager
    async def acquire(self, user_id: int) -> AsyncIterator[None]:
        """사용자와 전체 처리 자리를 점유하고 질문 처리 종료 시 해제한다.

        Args:
            user_id: 인증된 사용자 ID.

        Yields:
            질문 처리 구간의 점유.

        Raises:
            APIError: 사용자의 다른 질문이 처리 중이거나 전체 한도가 찬 경우.
        """
        # 확인과 추가 사이에 await가 없어야 중복 점유를 막을 수 있다.
        if user_id in self._active_users:
            raise APIError("CHAT_BUSY")
        if len(self._active_users) >= self._max_concurrent_requests:
            raise APIError("SERVER_BUSY")
        self._active_users.add(user_id)
        try:
            yield
        finally:
            self._active_users.remove(user_id)
