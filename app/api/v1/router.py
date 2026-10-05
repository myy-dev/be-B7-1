from fastapi import APIRouter
from sqlalchemy import text

from app.api.dependencies import DBSession
from app.api.v1.admin import router as admin_router
from app.api.v1.endpoints.chats import router as chats_router

router = APIRouter()
router.include_router(admin_router)
router.include_router(chats_router)


@router.get("/health", tags=["health"])
async def health_check(db: DBSession) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
