from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router, health_router
from app.clients.ai import AIClient
from app.core.config import get_settings
from app.core.database import create_db_and_tables, engine
from app.core.errors import configure_request_processing


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await create_db_and_tables()
        client = AIClient(
            settings.openai_api_key,
            settings.openai_model,
            settings.ai_timeout_seconds,
        )
        app.state.ai_client = client
        try:
            yield
        finally:
            await client.close()
    finally:
        await engine.dispose()


app = FastAPI(title="B7-1 API", lifespan=lifespan)
settings = get_settings()

# 프론트(React)는 별도 오리진(기본 localhost:5173)이라 브라우저가 CORS를 적용한다.
# 허용 오리진을 등록해 두지 않으면 브라우저가 실제 요청 전에 보내는 프리플라이트
# (OPTIONS)를 막아 관리자 화면 호출이 전부 실패한다. 허용 오리진은 설정값
# (Settings.cors_origins, 기본 개발·배포 주소)으로 두어 배포에서 .env로 바꾼다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
configure_request_processing(app, settings.system_log_path)

# /health는 접두어 없이 루트로 둔다(배포·모니터링이 관례적으로 /health를 찾는다).
# 나머지 API(관리자 포함)는 버전 접두어 /api/v1 아래로 모은다.
app.include_router(health_router)
app.include_router(api_router, prefix="/api/v1")
