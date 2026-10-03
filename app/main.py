from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import router
from app.core.database import create_db_and_tables, engine
from app.core.errors import configure_request_processing


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="B7-1 API", lifespan=lifespan)
configure_request_processing(app)
app.include_router(router)
