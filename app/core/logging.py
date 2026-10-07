"""원문이나 인증 정보를 포함하지 않는 요청·처리 이벤트 로그를 제공한다."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.core.request_context import request_id_context

LogEvent = Literal[
    "request_received",
    "request_completed",
    "request_failed",
    "api_error",
    "ai_call_started",
    "ai_call_succeeded",
    "ai_call_failed",
    "db_save_succeeded",
    "db_save_failed",
]


class EventLogFormatter(logging.Formatter):
    """허용된 메타데이터만 JSON으로 출력한다."""

    def format(self, record: logging.LogRecord) -> str:
        """이벤트와 허용된 필드를 JSON 로그 한 줄로 변환한다.

        Args:
            record: 처리 이벤트를 담은 로그 레코드.

        Returns:
            원문과 스택 트레이스를 제외한 JSON 문자열.
        """
        fields = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for name in (
            "request_id",
            "user_id",
            "chat_id",
            "result",
            "error_code",
            "duration_ms",
            "http_status",
            "exception_type",
        ):
            fields[name] = getattr(record, name, None)
        return json.dumps(fields, ensure_ascii=False)


def configure_logging(log_path: str | None = None) -> None:
    """애플리케이션 이벤트 로그를 JSON 출력과 파일에 연결한다.

    Args:
        log_path: 관리자 조회용 JSONL 파일 경로. None이면 표준 출력만 사용한다.
    """
    logger = logging.getLogger("app.events")
    if not any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.setFormatter(EventLogFormatter())
        logger.addHandler(handler)
    if log_path is not None:
        path = Path(log_path)
        resolved_path = str(path.absolute())
        has_file_handler = any(
            getattr(handler, "_app_log_path", None) == resolved_path
            for handler in logger.handlers
        )
        if not has_file_handler:
            for handler in list(logger.handlers):
                if getattr(handler, "_app_log_path", None) is not None:
                    logger.removeHandler(handler)
                    handler.close()
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(path, encoding="utf-8")
            setattr(file_handler, "_app_log_path", resolved_path)
            file_handler.setFormatter(EventLogFormatter())
            logger.addHandler(file_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_event(
    event: LogEvent,
    *,
    request_id: UUID | None = None,
    user_id: str | None = None,
    chat_id: UUID | None = None,
    result: Literal["success", "failure"] | None = None,
    error_code: str | None = None,
    duration_ms: float | None = None,
    http_status: int | None = None,
    exception_type: str | None = None,
) -> None:
    """현재 요청의 식별자로 처리 이벤트를 기록한다.

    Args:
        event: 기록할 처리 단계.
        request_id: 명시적으로 사용할 요청 식별자. 없으면 현재 요청 값을 사용한다.
        user_id: 인증 연동 후 전달하는 사용자 식별자의 문자열 표현.
        chat_id: 검증된 채팅방 식별자.
        result: 처리 결과.
        error_code: AI·채팅 또는 기존 관리자 API의 실패 코드.
        duration_ms: 요청 또는 AI 처리에 걸린 밀리초.
        http_status: HTTP 응답 상태.
        exception_type: 원문을 제외한 예외 클래스 이름.
    """
    current_id = request_id or request_id_context.get()
    logging.getLogger("app.events").log(
        logging.ERROR if result == "failure" else logging.INFO,
        event,
        extra={
            "request_id": str(current_id) if current_id else None,
            "user_id": user_id,
            "chat_id": str(chat_id) if chat_id else None,
            "result": result,
            "error_code": error_code,
            "duration_ms": duration_ms,
            "http_status": http_status,
            "exception_type": exception_type,
        },
    )
