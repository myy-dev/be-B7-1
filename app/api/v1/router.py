from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin import router as admin_router
from app.core.database import get_db

# 버전 접두어(/api/v1) 아래로 모을 API. main.py에서 prefix를 붙여 등록한다.
api_router = APIRouter()
api_router.include_router(admin_router)

# 접두어 없이 루트에 두는 헬스 체크. 배포·모니터링이 관례적으로 /health를 찾는다.
health_router = APIRouter()


@health_router.get("/health", tags=["health"])
async def health_check(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
