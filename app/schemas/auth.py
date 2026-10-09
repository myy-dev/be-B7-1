import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.core.datetimes import UtcDateTime


# 회원가입 입력 검증: 아이디·비밀번호·이름의 규칙을 검사하고 추가 필드를 거절한다.
class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=4, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
    password: SecretStr = Field(
        min_length=8,
        max_length=128,
        description="영문·숫자·특수문자를 각각 포함한 8~128자. 공백은 허용하지 않음",
    )
    name: str = Field(min_length=1, max_length=50)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        if re.fullmatch(
            r"(?=.*[a-zA-Z])(?=.*[0-9])(?=.*[!-/:-@\[-`{-~])[!-~]{8,128}",
            value.get_secret_value(),
        ) is None:
            raise ValueError(
                "비밀번호는 영문, 숫자, 특수문자를 각각 포함한 "
                "8~128자여야 하며 공백은 사용할 수 없습니다."
            )
        return value

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


# 회원가입 응답: 비밀번호와 해시를 제외한 회원 정보만 반환한다.
class SignupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    name: str
    created_at: UtcDateTime


# 로그인 API 구현: 아이디·비밀번호를 검증하고 아이디를 소문자로 통일한다.
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=4, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
    password: SecretStr = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()


# 로그인 API 구현: access token, 토큰 타입과 만료 시간(초)을 반환한다.
class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
