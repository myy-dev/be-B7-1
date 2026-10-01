"""관리자 조회 API.

관리자 화면이 회원·대화 기록·세션·시스템 로그를 조회하는 창구다. 목록은
공통 페이지 형식으로 돌려주고, 자세한 응답 필드는 schemas/admin.py에 있다.

접근 제어는 라우터 공통 의존성(require_admin)에서 한 번만 걸고, 오류는
core/errors.py 형식으로 통일한다. size 상한으로 한 번에 주는 양도 제한한다.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.v1.admin_deps import get_admin_service, require_admin
from app.core.pagination import Page, make_page
from app.schemas.admin import (
    ChatLogItem,
    SessionDetail,
    SessionItem,
    SystemLogItem,
    UserDetail,
    UserSummary,
)
from app.services.admin_service import AdminService

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


@router.get("/users", response_model=Page[UserSummary])
async def list_users(
    service: Annotated[AdminService, Depends(get_admin_service)],
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    items, total = await service.list_users(page, size)
    return make_page(items, total, page, size)


@router.get("/users/{user_id}", response_model=UserDetail)
async def get_user(
    user_id: int,
    service: Annotated[AdminService, Depends(get_admin_service)],
):
    return await service.get_user(user_id)


@router.get("/logs", response_model=Page[ChatLogItem])
async def list_logs(
    service: Annotated[AdminService, Depends(get_admin_service)],
    user_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    items, total = await service.list_logs(user_id, start, end, page, size)
    return make_page(items, total, page, size)


@router.get("/sessions", response_model=Page[SessionItem])
async def list_sessions(
    service: Annotated[AdminService, Depends(get_admin_service)],
    user_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    items, total = await service.list_sessions(user_id, page, size)
    return make_page(items, total, page, size)


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: int,
    service: Annotated[AdminService, Depends(get_admin_service)],
):
    return await service.get_session(session_id)


@router.get("/system-logs", response_model=Page[SystemLogItem])
async def list_system_logs(
    service: Annotated[AdminService, Depends(get_admin_service)],
    level: str | None = None,
    event: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    items, total = await service.list_system_logs(level, event, start, end, page, size)
    return make_page(items, total, page, size)
