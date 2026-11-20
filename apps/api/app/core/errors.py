"""Application errors and the handlers that turn them into typed responses.

Every non-2xx response uses the `ErrorResponse` envelope, so clients have one error
shape to parse regardless of where the failure originated.
"""

from collections.abc import Mapping, Sequence
from http import HTTPStatus

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.errors import ErrorBody, ErrorDetail, ErrorResponse

logger = structlog.get_logger(__name__)

INTERNAL_ERROR_CODE = "internal_error"
INTERNAL_ERROR_MESSAGE = "An unexpected error occurred."


class AppError(Exception):
    """Base class for expected failures that map to a specific API error response."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    code: str = INTERNAL_ERROR_CODE

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DependencyUnavailableError(AppError):
    """A backing service the request depends on cannot be reached."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "dependency_unavailable"


def build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    details: Sequence[ErrorDetail] = (),
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=request_id, details=list(details))
    )
    return JSONResponse(
        # int() so HTTPStatus members are sent and logged as plain integers.
        status_code=int(status_code),
        content=body.model_dump(mode="json"),
        headers=dict(headers) if headers else None,
    )


def _request_id(request: Request) -> str:
    # Set by RequestContextMiddleware, which wraps every HTTP request.
    request_id: str = request.state.request_id
    return request_id


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    logger.warning("request.app_error", code=exc.code, status_code=int(exc.status_code))
    return build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        request_id=_request_id(request),
    )


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    status = HTTPStatus(exc.status_code)
    return build_error_response(
        status_code=exc.status_code,
        code=status.phrase.lower().replace(" ", "_"),
        message=str(exc.detail) if exc.detail else status.phrase,
        request_id=_request_id(request),
        headers=exc.headers,
    )


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # The rejected input is deliberately not echoed back: it may contain secrets.
    details = [
        ErrorDetail(
            field=".".join(str(part) for part in error["loc"]),
            message=error["msg"],
            type=error["type"],
        )
        for error in exc.errors()
    ]
    return build_error_response(
        status_code=HTTPStatus.UNPROCESSABLE_CONTENT,
        code="validation_error",
        message="Request validation failed.",
        request_id=_request_id(request),
        details=details,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers for expected errors.

    Unexpected exceptions are intentionally not registered here. They propagate to
    RequestContextMiddleware, which logs them once and returns the same envelope.
    """
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
