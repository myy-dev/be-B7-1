from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.core.datetimes import UtcDateTime


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=4, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
    password: SecretStr = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=50)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SignupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    name: str
    created_at: UtcDateTime


# 로그인 API 구현
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=4, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
    password: SecretStr = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()


# 로그인 API 구현
class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
