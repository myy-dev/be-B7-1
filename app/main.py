from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router, health_router
from app.core.config import get_settings
from app.core.database import create_db_and_tables, engine
from app.core.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="B7-1 API", lifespan=lifespan)

# 프론트(React)는 별도 오리진(기본 localhost:5173)이라 브라우저가 CORS를 적용한다.
# 허용 오리진을 등록해 두지 않으면 브라우저가 실제 요청 전에 보내는 프리플라이트
# (OPTIONS)를 막아 관리자 화면 호출이 전부 실패한다. 허용 오리진은 설정값
# (Settings.cors_origins, 기본 로컬 개발 주소)으로 두어 배포에서 .env로 바꾼다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 요청마다 고유 식별자(request_id)를 붙인다. 오류 응답(core/errors.py)이 이 값을
# 실어 보내므로, 사용자 문의나 로그에서 한 요청을 끝까지 따라갈 수 있다.
# 미들웨어로 두어 모든 요청에 빠짐없이 적용한다.
@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    return await call_next(request)


# /health는 접두어 없이 루트로 둔다(배포·모니터링이 관례적으로 /health를 찾는다).
# 나머지 API(관리자 포함)는 버전 접두어 /api/v1 아래로 모은다.
app.include_router(health_router)
app.include_router(api_router, prefix="/api/v1")
register_exception_handlers(app)
