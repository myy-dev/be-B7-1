"""관리자 조회의 실제 DB 구현.

회원·대화·세션을 실제 DB에서 읽는다. 서비스·라우터는 그대로 두고
`get_admin_service`에서 이 구현으로 갈아끼운다. 읽기만 하며, 세션 생성·삭제는
채팅 쪽 책임이다.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, ChatLog
from app.models.user import User
from app.repositories.admin_repositories import (
    ChatLogRepository,
    SessionRepository,
    UserRepository,
)


def _user_dict(user: User) -> dict:
    # ORM 객체를 응답 스키마가 받는 dict로 바꾼다. 비밀번호·해시는 여기서 떨어진다.
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


def _log_dict(log: ChatLog) -> dict:
    # UUID는 str로 바꿔야 JSON 직렬화가 된다. 스키마 필드와 1:1이다.
    return {
        "request_id": str(log.request_id),
        "chat_id": str(log.chat_id),
        "question": log.question,
        "answer": log.answer,
        "status": log.status,
        "error_code": log.error_code,
        "created_at": log.created_at,
        "finished_at": log.finished_at,
    }


# 관리자 회원 조회: 실제 users 테이블에서 회원 목록과 상세 정보를 조회한다.
class DbUserRepository(UserRepository):
    """`users` 테이블에서 비밀번호·해시 없이 공개 필드만 읽는다."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 관리자 회원 목록: 전체 회원 수와 페이지에 해당하는 공개 회원 정보를 조회한다.
    async def list_users(self, page: int, size: int) -> tuple[list[dict], int]:
        total = await self.session.scalar(select(func.count(User.id))) or 0
        begin = max(page - 1, 0) * max(size, 1)
        rows = await self.session.scalars(
            select(User).order_by(User.id.asc()).offset(begin).limit(max(size, 1))
        )
        return [_user_dict(u) for u in rows.all()], total

    # 관리자 회원 상세: 회원 ID로 조회하고 비밀번호·해시를 제외한 정보를 반환한다.
    async def get_user(self, user_id: int) -> dict | None:
        user = await self.session.scalar(select(User).where(User.id == user_id))
        return _user_dict(user) if user is not None else None

    async def update_role(self, user_id: int, role: str) -> dict | None:
        user = await self.session.scalar(select(User).where(User.id == user_id))
        if user is None:
            return None
        user.role = role
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return {"id": user.id, "username": user.username, "role": user.role}


class DbChatLogRepository(ChatLogRepository):
    """`chat_logs`에서 회원·기간 조건으로 대화 기록을 읽는다.

    회원 조건은 `chats.user_id`로 소유 채팅방을 먼저 좁힌다.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_logs(
        self,
        user_id: int | None,
        start: datetime | None,
        end: datetime | None,
        page: int,
        size: int,
    ) -> tuple[list[dict], int]:
        query = select(ChatLog)
        count_query = select(func.count(ChatLog.request_id))
        if user_id is not None:
            owned = select(Chat.chat_id).where(Chat.user_id == user_id)
            query = query.where(ChatLog.chat_id.in_(owned))
            count_query = count_query.where(ChatLog.chat_id.in_(owned))
        if start is not None:
            query = query.where(ChatLog.created_at >= start)
            count_query = count_query.where(ChatLog.created_at >= start)
        if end is not None:
            query = query.where(ChatLog.created_at <= end)
            count_query = count_query.where(ChatLog.created_at <= end)
        total = await self.session.scalar(count_query) or 0
        begin = max(page - 1, 0) * max(size, 1)
        rows = await self.session.scalars(
            query.order_by(ChatLog.created_at.desc(), ChatLog.request_id.desc())
            .offset(begin)
            .limit(max(size, 1))
        )
        return [_log_dict(r) for r in rows.all()], total


class DbSessionRepository(SessionRepository):
    """`chats` 목록·상세와 `chat_logs` 메시지를 읽는다."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_sessions(
        self, user_id: int, page: int, size: int
    ) -> tuple[list[dict], int]:
        # 세션마다 count·첫 질문을 따로 조회하면 N+1이 나므로, 상관 서브쿼리로
        # 한 번에 가져온다.
        # TODO(채팅 담당): chats에 title 컬럼이 생기면 파생을 걷어낸다.
        count_sq = (
            select(func.count(ChatLog.request_id))
            .where(ChatLog.chat_id == Chat.chat_id)
            .scalar_subquery()
        )
        first_sq = (
            select(ChatLog.question)
            .where(ChatLog.chat_id == Chat.chat_id)
            .order_by(ChatLog.created_at.asc(), ChatLog.request_id.asc())
            .limit(1)
            .scalar_subquery()
        )
        total = (
            await self.session.scalar(
                select(func.count(Chat.chat_id)).where(Chat.user_id == user_id)
            )
            or 0
        )
        begin = max(page - 1, 0) * max(size, 1)
        rows = await self.session.execute(
            select(Chat, count_sq, first_sq)
            .where(Chat.user_id == user_id)
            .order_by(Chat.created_at.desc(), Chat.chat_id.desc())
            .offset(begin)
            .limit(max(size, 1))
        )
        items = [
            {
                "chat_id": str(chat.chat_id),
                "user_id": chat.user_id,
                "title": first or "",
                "created_at": chat.created_at,
                "message_count": count or 0,
            }
            for chat, count, first in rows.all()
        ]
        return items, total

    async def get_session(self, chat_id: str) -> dict | None:
        try:
            key = UUID(chat_id)
        except ValueError:
            return None
        chat = await self.session.scalar(select(Chat).where(Chat.chat_id == key))
        if chat is None:
            return None
        rows = await self.session.scalars(
            select(ChatLog)
            .where(ChatLog.chat_id == key)
            .order_by(ChatLog.created_at.asc(), ChatLog.request_id.asc())
        )
        messages = [_log_dict(r) for r in rows.all()]
        # TODO(채팅 담당): chats에 title 컬럼이 생기면 파생을 걷어낸다.
        return {
            "chat_id": str(chat.chat_id),
            "user_id": chat.user_id,
            "title": messages[0]["question"] if messages else "",
            "created_at": chat.created_at,
            "message_count": len(messages),
            "messages": messages,
        }
