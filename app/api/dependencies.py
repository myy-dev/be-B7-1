"""여러 라우터에서 재사용하는 요청·DB 의존성을 정의한다."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db


def get_request_id(request: Request) -> UUID:
    """미들웨어가 생성한 현재 요청의 식별자를 반환한다.

    Args:
        request: 현재 HTTP 요청.

    Returns:
        서버에서 생성한 UUID4 식별자.
    """
    return request.state.request_id


DBSession = Annotated[AsyncSession, Depends(get_db)]
RequestId = Annotated[UUID, Depends(get_request_id)]
