from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, LoginResponse, SignupRequest, SignupResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    return AuthService(UserRepository(db))


@router.post(
    "/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED
)
async def signup(
    data: SignupRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
):
    return await service.signup(data)


# 로그인 API 구현
@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
):
    return await service.login(data)
