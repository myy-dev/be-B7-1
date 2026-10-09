from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUserId, DBSession, bearer
from app.core.database import get_db
from app.core.security import decode_access_token_claims
from app.repositories.token_repository import TokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


# 회원 인증 서비스 구성: 요청의 DB 세션으로 회원 저장소와 서비스를 만든다.
def get_auth_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    return AuthService(UserRepository(db))


# 회원가입 API: POST /api/v1/auth/signup 요청을 가입 서비스로 전달한다.
@router.post(
    "/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED
)
async def signup(
    data: SignupRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
):
    return await service.signup(data)


# 로그인 API 구현: POST /api/v1/auth/login 요청을 로그인 서비스로 전달한다.
@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
):
    return await service.login(data)


# 로그아웃 API 구현: 현재 액세스 토큰을 폐기해 이후 요청에서 사용할 수 없게 한다.
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    user_id: CurrentUserId,
    db: DBSession,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> Response:
    claims = decode_access_token_claims(credentials.credentials)
    await TokenRepository(db).revoke(
        credentials.credentials, datetime.fromtimestamp(claims["exp"], UTC)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
