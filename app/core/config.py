from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str
    openai_model: str = "gpt-6-luna"
    ai_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    # 시스템 이벤트 로그(JSONL) 위치. 배포에서는 한 파일에 쌓이게 맞춘다.
    system_log_path: str = "logs/system.jsonl"
    # CORS_ORIGINS 환경변수는 쉼표로 구분한다: CORS_ORIGINS=http://a,http://b
    # 기본값은 로컬 개발 주소와 실제 배포 주소를 함께 둔다. 배포 프론트는 자체
    # 도메인과 Vercel 주소 두 곳으로 열린다.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://www.quackquack-e.duckdns.org",
        "https://b7-1-two.vercel.app",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """쉼표로 구분된 환경변수 문자열을 목록으로 바꾼다.

        설정값은 환경변수에서 오면 항상 문자열 하나로 들어온다. 예를 들어
        CORS_ORIGINS=http://a,http://b를 그대로 두면 목록이 아니라 "http://a,http://b"
        한 덩어리가 되어 오리진 매칭이 실패한다. pydantic의 field_validator는
        타입 변환 전(mode="before")에 값을 가공하는 자리라, 여기서 문자열을
        쉼표로 쪼개고 공백을 제거한다. 목록으로 직접 넘어온 경우는 그대로 둔다.
        """
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
