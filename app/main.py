from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import router
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
app.include_router(router)
register_exception_handlers(app)
