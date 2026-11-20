"""Request-scoped context: request IDs, access logging, and the last-resort error handler."""

import re
import time
import uuid
from http import HTTPStatus

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import INTERNAL_ERROR_CODE, INTERNAL_ERROR_MESSAGE, build_error_response

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# A caller-supplied ID is written to logs and echoed in responses, so only a
# conservative character set is accepted. Anything else is replaced.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")


def _resolve_request_id(scope: Scope) -> str:
    supplied = Headers(scope=scope).get(REQUEST_ID_HEADER)
    if supplied and _VALID_REQUEST_ID.fullmatch(supplied):
        return supplied
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """Pure ASGI middleware that gives every HTTP request a correlation ID.

    For each request it:
    - accepts a well-formed `X-Request-ID` header or generates a new ID,
    - binds the ID to the logging context and exposes it as `request.state.request_id`,
    - returns the ID in the `X-Request-ID` response header,
    - logs one structured line when the request finishes,
    - converts an unhandled exception into the standard error envelope, logging the
      traceback exactly once.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _resolve_request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id

        started_at = time.perf_counter()
        status_code = int(HTTPStatus.INTERNAL_SERVER_ERROR)
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception:
                logger.exception("request.unhandled_exception")
                if response_started:
                    # Headers are already on the wire; the response cannot be replaced.
                    raise
                response = build_error_response(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    code=INTERNAL_ERROR_CODE,
                    message=INTERNAL_ERROR_MESSAGE,
                    request_id=request_id,
                )
                await response(scope, receive, send_with_request_id)
            finally:
                logger.info(
                    "request.completed",
                    method=scope["method"],
                    # The query string is omitted on purpose: it can carry secrets
                    # such as OAuth authorization codes.
                    path=scope["path"],
                    status_code=status_code,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                )
