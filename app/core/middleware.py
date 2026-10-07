"""HTTP 요청마다 UUID4 식별자와 처리 이벤트를 생성한다."""

from time import perf_counter
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import log_event
from app.core.request_context import request_id_context


class RequestContextMiddleware:
    """요청 식별자를 상태·컨텍스트·응답 헤더에 연결한다."""

    def __init__(self, app: ASGIApp) -> None:
        """내부 ASGI 애플리케이션을 보관한다.

        Args:
            app: 요청을 처리할 내부 애플리케이션.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """HTTP 요청의 시작·종료를 기록하고 요청 컨텍스트를 정리한다.

        Args:
            scope: ASGI 요청 정보.
            receive: 요청 메시지 수신 함수.
            send: 응답 메시지 전송 함수.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4()
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)
        started_at = perf_counter()
        status_code = 500
        log_event("request_received")

        async def send_response(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", str(request_id).encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception as exc:
            log_event(
                "request_failed",
                user_id=_user_id(scope),
                chat_id=scope["state"].get("chat_id"),
                result="failure",
                error_code="INTERNAL_ERROR",
                http_status=500,
                duration_ms=round((perf_counter() - started_at) * 1000, 3),
                exception_type=type(exc).__name__,
            )
            raise
        else:
            log_event(
                "request_completed",
                user_id=_user_id(scope),
                chat_id=scope["state"].get("chat_id"),
                result="success" if status_code < 400 else "failure",
                error_code=scope["state"].get("error_code"),
                duration_ms=round((perf_counter() - started_at) * 1000, 3),
                http_status=status_code,
            )
        finally:
            request_id_context.reset(token)


def _user_id(scope: Scope) -> str | None:
    value = scope["state"].get("user_id")
    return str(value) if value is not None else None
