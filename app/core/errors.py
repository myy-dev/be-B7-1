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
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """서비스 계층이 던지는 오류. code는 프론트가 분기하는 식별자다."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def error_body(request: Request, code: str, message: str) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request.state.request_id,
        }
    }


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(request, exc.code, exc.message),
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body(request, "INVALID_INPUT", "요청 값이 올바르지 않습니다."),
    )


async def http_error_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    # 라우터 밖(없는 경로·허용 안 된 메서드)에서 나는 오류도 같은 형식으로 맞춘다.
    message = (
        exc.detail if isinstance(exc.detail, str) else "요청을 처리하지 못했습니다."
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(request, http_status_code(exc.status_code), message),
    )


def http_status_code(status: int) -> str:
    if status == 404:
        return "NOT_FOUND"
    if status == 405:
        return "METHOD_NOT_ALLOWED"
    return "HTTP_ERROR"


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=error_body(request, "INTERNAL_ERROR", "서버 내부 오류가 발생했습니다."),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
