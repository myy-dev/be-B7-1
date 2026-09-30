from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router
from app.core.database import create_db_and_tables, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="B7-1 API", lifespan=lifespan)
app.include_router(router)
