from fastapi import APIRouter
from sqlalchemy import text

from app.api.dependencies import DBSession
from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.endpoints.chat import router as chat_router

# 버전 접두어(/api/v1) 아래로 모을 API. main.py에서 prefix를 붙여 등록한다.
api_router = APIRouter()
api_router.include_router(admin_router)
api_router.include_router(auth_router)
api_router.include_router(chat_router)

# 접두어 없이 루트에 두는 헬스 체크. 배포·모니터링이 관례적으로 /health를 찾는다.
health_router = APIRouter()


@health_router.get("/health", tags=["health"])
async def health_check(db: DBSession) -> dict[str, str]:
    """DB 연결 상태를 확인한다.

    Args:
        db: 요청에 주입된 DB 세션.

    Returns:
        DB 조회에 성공한 경우 정상 상태.
    """
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
