from datetime import UTC, datetime

from app.repositories.admin_repositories import (
    ChatLogRepository,
    SessionRepository,
    SystemLogRepository,
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

LOGS = [
    {
        "id": 1,
        "user_id": 1,
        "session_id": 1,
        "question": "배포 방법 알려줘",
        "response": "Vercel과 백엔드 배포 경로를 안내합니다.",
        "created_at": NOW,
    },
    {
        "id": 2,
        "user_id": 1,
        "session_id": 1,
        "question": "아까 뭐 물어봤지?",
        "response": "직전에 배포 방법을 물어보셨습니다.",
        "created_at": NOW,
    },
]

SESSIONS = [
    {
        "id": 1,
        "user_id": 1,
        "title": "배포 문의",
        "created_at": NOW,
        "message_count": 2,
    },
]


class MockUserRepository(UserRepository):
    async def list_users(self, page: int, size: int) -> tuple[list[dict], int]:
        return USERS, len(USERS)

    async def get_user(self, user_id: int) -> dict | None:
        return next((u for u in USERS if u["id"] == user_id), None)


class MockChatLogRepository(ChatLogRepository):
    async def list_logs(
        self, user_id, start, end, page, size
    ) -> tuple[list[dict], int]:
        rows = LOGS
        if user_id is not None:
            rows = [r for r in rows if r["user_id"] == user_id]
        return rows, len(rows)


class MockSessionRepository(SessionRepository):
    async def list_sessions(
        self, user_id: int, page: int, size: int
    ) -> tuple[list[dict], int]:
        rows = [s for s in SESSIONS if s["user_id"] == user_id]
        return rows, len(rows)

    async def get_session(self, session_id: int) -> dict | None:
        session = next((s for s in SESSIONS if s["id"] == session_id), None)
        if session is None:
            return None
        messages = [m for m in LOGS if m["session_id"] == session_id]
        return {**session, "messages": messages}


class MockSystemLogRepository(SystemLogRepository):
    async def query(
        self, level, event, start, end, page, size
    ) -> tuple[list[dict], int]:
        rows = [
            {
                "timestamp": NOW,
                "level": "INFO",
                "event": "ai_call_started",
                "request_id": "abc-123",
                "user_id": 1,
            }
        ]
        if level:
            rows = [r for r in rows if r["level"] == level]
        if event:
            rows = [r for r in rows if r["event"] == event]
        return rows, len(rows)
