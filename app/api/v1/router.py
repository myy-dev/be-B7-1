from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin import router as admin_router
from app.core.database import get_db

router = APIRouter()
router.include_router(admin_router)


@router.get("/health", tags=["health"])
async def health_check(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}