# TODO(회원·채팅 담당): 스키마 확정 후 실제 DB 조회로 바꾸고 이 파일을 지운다.

from datetime import UTC, datetime

from app.core.pagination import slice_page
from app.repositories.admin_repositories import (
    ChatLogRepository,
    SessionRepository,
    UserRepository,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)

USERS = [
    {
        "id": 1,
        "username": "user_a",
        "name": "사용자A",
        "created_at": NOW,
        "last_login_at": NOW,
    },
    {
        "id": 2,
        "username": "user_b",
        "name": "사용자B",
        "created_at": NOW,
        "last_login_at": None,
    },
]

_CHAT_ID = "e6100748-b7f0-48e6-a264-7c20a748cf93"

LOGS = [
    {
        "request_id": "16fd2706-8baf-433b-82eb-8c7fada847da",
        "chat_id": _CHAT_ID,
        "question": "배포 방법 알려줘",
        "answer": "Vercel과 백엔드 배포 경로를 안내합니다.",
        "status": "completed",
        "error_code": None,
        "created_at": NOW,
        "finished_at": NOW,
    },
    {
        "request_id": "26fd2706-8baf-433b-82eb-8c7fada847db",
        "chat_id": _CHAT_ID,
        "question": "아까 뭐 물어봤지?",
        "answer": None,
        "status": "failed",
        "error_code": "AI_TIMEOUT",
        "created_at": NOW,
        "finished_at": NOW,
    },
]

SESSIONS = [
    {
        "chat_id": _CHAT_ID,
        "user_id": 1,
        "title": "배포 문의",
        "created_at": NOW,
        "message_count": 2,
    },
]


class MockUserRepository(UserRepository):
    async def list_users(self, page: int, size: int) -> tuple[list[dict], int]:
        return slice_page(USERS, page, size)

    async def get_user(self, user_id: int) -> dict | None:
        return next((u for u in USERS if u["id"] == user_id), None)


class MockChatLogRepository(ChatLogRepository):
    async def list_logs(
        self, user_id, start, end, page, size
    ) -> tuple[list[dict], int]:
        rows = LOGS
        if user_id is not None:
            owned = {s["chat_id"] for s in SESSIONS if s["user_id"] == user_id}
            rows = [r for r in rows if r["chat_id"] in owned]
        return slice_page(rows, page, size)


class MockSessionRepository(SessionRepository):
    async def list_sessions(
        self, user_id: int, page: int, size: int
    ) -> tuple[list[dict], int]:
        rows = [s for s in SESSIONS if s["user_id"] == user_id]
        return slice_page(rows, page, size)

    async def get_session(self, chat_id: str) -> dict | None:
        session = next((s for s in SESSIONS if s["chat_id"] == chat_id), None)
        if session is None:
            return None
        messages = [m for m in LOGS if m["chat_id"] == chat_id]
        return {**session, "messages": messages}
