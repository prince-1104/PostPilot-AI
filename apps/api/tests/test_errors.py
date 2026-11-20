"""Every failure mode returns the same typed error envelope."""

import io

import httpx
from fastapi import FastAPI

from app.core.errors import AppError


def _assert_error_envelope(response: httpx.Response, *, status_code: int, code: str) -> dict:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "request_id", "details"}
    assert error["code"] == code
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error


async def test_unknown_route_returns_not_found_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    _assert_error_envelope(response, status_code=404, code="not_found")


async def test_unsupported_method_returns_envelope_and_allow_header(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/api/v1/health/live")

    _assert_error_envelope(response, status_code=405, code="method_not_allowed")
    assert response.headers["Allow"] == "GET"


async def test_validation_failure_lists_fields_without_echoing_input(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    @app.get("/api/v1/test-only/items/{item_id}")
    async def read_item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    response = await client.get("/api/v1/test-only/items/not-a-number")

    error = _assert_error_envelope(response, status_code=422, code="validation_error")
    assert error["details"] == [
        {
            "field": "path.item_id",
            "message": "Input should be a valid integer, unable to parse string as an integer",
            "type": "int_parsing",
        }
    ]
    assert "not-a-number" not in response.text


async def test_app_error_maps_to_its_status_and_code(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    class ConflictError(AppError):
        status_code = 409
        code = "conflict"

    @app.get("/api/v1/test-only/conflict")
    async def conflict() -> None:
        raise ConflictError("The resource was modified by another request.")

    response = await client.get("/api/v1/test-only/conflict")

    error = _assert_error_envelope(response, status_code=409, code="conflict")
    assert error["message"] == "The resource was modified by another request."


async def test_unhandled_exception_returns_generic_envelope_and_is_logged_once(
    app: FastAPI, client: httpx.AsyncClient, log_output: io.StringIO
) -> None:
    @app.get("/api/v1/test-only/crash")
    async def crash() -> None:
        raise RuntimeError("internal detail that must not reach the client")

    response = await client.get("/api/v1/test-only/crash")

    error = _assert_error_envelope(response, status_code=500, code="internal_error")
    assert error["message"] == "An unexpected error occurred."
    assert "internal detail" not in response.text

    # The traceback is not swallowed: it is logged, exactly once, for operators.
    logs = log_output.getvalue()
    assert logs.count("request.unhandled_exception") == 1
    assert "internal detail that must not reach the client" in logs
