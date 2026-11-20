"""Request ID propagation and CORS behaviour."""

import io
import json
import re

import httpx
import pytest

from tests.conftest import ALLOWED_ORIGIN

LIVE_URL = "/api/v1/health/live"


async def test_request_id_is_generated_when_absent(client: httpx.AsyncClient) -> None:
    response = await client.get(LIVE_URL)

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


async def test_well_formed_request_id_is_preserved(client: httpx.AsyncClient) -> None:
    response = await client.get(LIVE_URL, headers={"X-Request-ID": "trace-1234.abcd_EF"})

    assert response.headers["X-Request-ID"] == "trace-1234.abcd_EF"


@pytest.mark.parametrize("supplied", ["has spaces", "semi;colon", '{"json":1}', "x" * 129])
async def test_malformed_request_id_is_replaced(client: httpx.AsyncClient, supplied: str) -> None:
    response = await client.get(LIVE_URL, headers={"X-Request-ID": supplied})

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


async def test_request_log_carries_request_id_and_omits_query_string(
    client: httpx.AsyncClient, log_output: io.StringIO
) -> None:
    response = await client.get(f"{LIVE_URL}?code=value-that-must-not-be-logged")

    output = log_output.getvalue()
    records = [json.loads(line) for line in output.splitlines()]
    completed = [record for record in records if record["event"] == "request.completed"]

    assert len(completed) == 1
    assert completed[0]["request_id"] == response.headers["X-Request-ID"]
    assert completed[0]["method"] == "GET"
    assert completed[0]["path"] == LIVE_URL
    assert completed[0]["status_code"] == 200
    # Holds for every logger sharing the handler, including the HTTP client used by
    # this test, which logs the full request URL.
    assert "value-that-must-not-be-logged" not in output


async def test_cors_allows_configured_origin_with_credentials(client: httpx.AsyncClient) -> None:
    response = await client.get(LIVE_URL, headers={"Origin": ALLOWED_ORIGIN})

    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert "X-Request-ID" in response.headers["Access-Control-Expose-Headers"]


async def test_cors_preflight_succeeds_for_configured_origin(client: httpx.AsyncClient) -> None:
    response = await client.options(
        LIVE_URL,
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN


async def test_cors_does_not_allow_unlisted_origin(client: httpx.AsyncClient) -> None:
    unlisted = {"Origin": "https://evil.example.com"}

    simple = await client.get(LIVE_URL, headers=unlisted)
    preflight = await client.options(
        LIVE_URL, headers={**unlisted, "Access-Control-Request-Method": "GET"}
    )

    assert "Access-Control-Allow-Origin" not in simple.headers
    assert preflight.status_code == 400
    assert "Access-Control-Allow-Origin" not in preflight.headers


async def test_cors_headers_are_present_on_error_responses(client: httpx.AsyncClient) -> None:
    # Without these headers a browser hides the error body from the frontend.
    response = await client.get("/api/v1/health/ready", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 503
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
