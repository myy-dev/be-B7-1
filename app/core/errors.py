"""에러 응답 형식.

프론트가 오류를 한 가지 모양으로 처리하도록, 모든 오류를
{"error": {"code", "message", "request_id"}} 형태로 내보낸다. request_id는
오류가 발생한 요청을 가리키며, 사용자 문의나 로그 대조에 쓴다. 서비스는
AppError를 던지고 여기 핸들러가 상태 코드와 본문으로 바꾼다. 프론트는 code로
분기하고 message를 그대로 보여줄 수 있다.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.responses import Response

from app.core.logging import configure_logging, log_event
from app.core.middleware import RequestContextMiddleware
from app.schemas.error import ErrorCode, ErrorResponse

ERROR_STATUS_CODES: dict[ErrorCode, int] = {
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "CHAT_NOT_FOUND": 404,
    "CHAT_BUSY": 409,
    "INVALID_INPUT": 422,
    "DB_ERROR": 500,
    "AI_UNAVAILABLE": 502,
    "AI_CONFIGURATION_ERROR": 503,
    "AI_TIMEOUT": 504,
}

ERROR_MESSAGES: dict[ErrorCode, str] = {
    "UNAUTHORIZED": "로그인이 필요합니다.",
    "FORBIDDEN": "접근 권한이 없습니다.",
    "CHAT_NOT_FOUND": "채팅방을 찾을 수 없습니다.",
    "CHAT_BUSY": "이전 질문을 처리 중입니다. 잠시 후 다시 시도해 주세요.",
    "INVALID_INPUT": "입력값을 확인해 주세요.",
    "DB_ERROR": "대화 데이터를 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "AI_UNAVAILABLE": "답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "AI_CONFIGURATION_ERROR": "AI 서비스 설정을 확인해야 합니다.",
    "AI_TIMEOUT": "응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
}


class AppError(Exception):
    """서비스 계층이 던지는 오류. code는 프론트가 분기하는 식별자다."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        """오류의 식별자, 안내 문구와 HTTP 상태를 보관한다.

        Args:
            code: 오류를 구분하는 식별자.
            message: 사용자에게 반환할 안내 문구.
            status_code: 오류 응답의 HTTP 상태.
        """
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class APIError(AppError):
    """AI·채팅 명세에 정의된 오류를 기존 공통 오류 체계로 전달한다."""

    def __init__(self, code: ErrorCode) -> None:
        """오류 코드에 맞는 상태와 고정 안내 문구를 설정한다.

        Args:
            code: AI·채팅 명세에 정의된 오류 코드.
        """
        self.api_code: ErrorCode = code
        super().__init__(code, ERROR_MESSAGES[code], ERROR_STATUS_CODES[code])


def internal_error() -> AppError:
    """처리하지 못한 예외의 공통 오류 정보를 반환한다.

    Returns:
        원본 예외 정보를 포함하지 않는 서버 내부 오류.
    """
    return AppError("INTERNAL_ERROR", "서버 내부 오류가 발생했습니다.", status_code=500)


def error_body(request: Request, code: str, message: str) -> dict[str, dict[str, str]]:
    """오류 코드를 요청 로그에 연결하고 공통 응답 본문을 생성한다.

    Args:
        request: 현재 HTTP 요청.
        code: 오류를 구분하는 식별자.
        message: 사용자에게 반환할 안내 문구.

    Returns:
        오류 코드, 안내 문구와 요청 식별자를 포함한 본문.
    """
    request.state.error_code = code
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": str(request.state.request_id),
        }
    }


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """서비스 오류를 지정된 상태와 공통 응답으로 변환한다.

    Args:
        request: 현재 HTTP 요청.
        exc: 서비스 계층에서 발생한 오류.

    Returns:
        서비스 오류의 상태와 안내 문구를 포함한 응답.
    """
    if not isinstance(exc, AppError):
        raise exc
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(request, exc.code, exc.message),
    )


async def http_error_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """경로·메서드 등 일반 HTTP 오류를 공통 형식으로 반환한다.

    Args:
        request: 현재 HTTP 요청.
        exc: 라우팅 또는 HTTP 처리에서 발생한 오류.

    Returns:
        상태 코드·안내 문구·요청 식별자를 포함한 응답.
    """
    message = (
        exc.detail if isinstance(exc.detail, str) else "요청을 처리하지 못했습니다."
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(request, http_status_code(exc.status_code), message),
        headers=exc.headers,
    )


def http_status_code(status: int) -> str:
    """일반 HTTP 상태에 대응하는 공통 오류 코드를 반환한다.

    Args:
        status: HTTP 오류 상태 코드.

    Returns:
        상태에 대응하는 오류 식별자.
    """
    if status == 404:
        return "NOT_FOUND"
    if status == 405:
        return "METHOD_NOT_ALLOWED"
    return "HTTP_ERROR"


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """처리하지 못한 예외의 원문을 제외하고 내부 오류 응답을 반환한다.

    Args:
        request: 현재 HTTP 요청.
        exc: 별도 핸들러가 없는 서버 예외.

    Returns:
        요청 식별자 헤더와 INTERNAL_ERROR 본문을 포함한 500 응답.
    """
    error = internal_error()
    return JSONResponse(
        status_code=error.status_code,
        content=error_body(request, error.code, error.message),
        headers={"X-Request-ID": str(request.state.request_id)},
    )


def _error_response(
    request: Request,
    code: ErrorCode,
    *,
    exception_type: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = request.state.request_id
    content = error_body(request, code, ERROR_MESSAGES[code])
    log_event(
        "db_save_failed" if code == "DB_ERROR" else "api_error",
        request_id=request_id,
        result="failure",
        error_code=code,
        exception_type=exception_type,
        http_status=ERROR_STATUS_CODES[code],
    )
    payload = ErrorResponse.model_validate(content)
    return JSONResponse(
        status_code=ERROR_STATUS_CODES[code],
        content=payload.model_dump(mode="json"),
        headers=headers,
    )


async def handle_api_error(request: Request, exc: Exception) -> JSONResponse:
    """Service 등에서 발생한 예상 가능한 처리 실패를 공통 응답으로 변환한다.

    Args:
        request: 현재 HTTP 요청.
        exc: 명세에 정의된 오류.

    Returns:
        오류 코드와 요청 식별자를 포함한 응답.
    """
    if not isinstance(exc, APIError):
        raise exc
    return _error_response(request, exc.api_code, exception_type=type(exc).__name__)


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """검증 오류에서 입력 원문을 제외하고 공통 422 응답을 반환한다.

    Args:
        request: 현재 HTTP 요청.
        exc: 경로·본문 등의 입력 검증 오류.

    Returns:
        INVALID_INPUT 오류 응답.
    """
    if not isinstance(exc, RequestValidationError):
        raise exc
    return _error_response(request, "INVALID_INPUT", exception_type=type(exc).__name__)


async def handle_database_error(request: Request, exc: Exception) -> JSONResponse:
    """SQL이나 매개변수 원문을 제외하고 공통 DB 오류 응답을 반환한다.

    Args:
        request: 현재 HTTP 요청.
        exc: SQLAlchemy 조회·저장 오류.

    Returns:
        DB_ERROR 오류 응답.
    """
    if not isinstance(exc, SQLAlchemyError):
        raise exc
    return _error_response(request, "DB_ERROR", exception_type=type(exc).__name__)


async def handle_http_error(request: Request, exc: Exception) -> Response:
    """인증·입력 오류를 명세에 맞추고 다른 HTTP 오류도 공통 형식으로 반환한다.

    Args:
        request: 현재 HTTP 요청.
        exc: 인증 의존성 등의 HTTP 오류.

    Returns:
        HTTP 상태와 요청 식별자를 포함한 공통 오류 응답.
    """
    if not isinstance(exc, HTTPException):
        raise exc
    code: ErrorCode
    if exc.status_code == 401:
        code = "UNAUTHORIZED"
    elif exc.status_code == 403:
        code = "FORBIDDEN"
    elif exc.status_code == 422:
        code = "INVALID_INPUT"
    else:
        return await http_error_handler(request, exc)
    return _error_response(
        request, code, exception_type=type(exc).__name__, headers=exc.headers
    )


def register_exception_handlers(app: FastAPI) -> None:
    """서비스·인증·입력·DB·일반 서버 오류 핸들러를 등록한다.

    Args:
        app: 오류 핸들러를 적용할 FastAPI 애플리케이션.
    """
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_exception_handler(APIError, handle_api_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(SQLAlchemyError, handle_database_error)
    app.add_exception_handler(HTTPException, handle_http_error)


def configure_request_processing(
    app: FastAPI, log_path: str | None = None
) -> None:
    """요청 미들웨어·이벤트 로그·공통 오류 핸들러를 등록한다.

    Args:
        app: 공통 처리를 적용할 FastAPI 애플리케이션.
        log_path: 관리자 조회용 이벤트 로그 파일 경로.
    """
    configure_logging(log_path)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
