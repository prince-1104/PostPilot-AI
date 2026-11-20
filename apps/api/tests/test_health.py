"""Liveness and readiness behaviour without a real database.

The readiness success path against real PostgreSQL lives in tests/integration.
"""

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.api.deps import get_session
from app.core.errors import DependencyUnavailableError
from app.services.health import check_database


class _HealthySession:
    """Stands in for a session whose query succeeds."""

    async def execute(self, _statement: object) -> None:
        return None


class _HangingSession:
    """Stands in for a session whose query never returns."""

    async def execute(self, _statement: object) -> None:
        await asyncio.sleep(60)


async def test_live_returns_alive_without_external_services(client: httpx.AsyncClient) -> None:
    # The configured database port is closed, so a 200 here proves liveness
    # does not depend on PostgreSQL.
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_ready_returns_ready_when_database_check_passes(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    async def healthy_session() -> AsyncIterator[_HealthySession]:
        yield _HealthySession()

    app.dependency_overrides[get_session] = healthy_session

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


async def test_ready_returns_503_when_database_is_unreachable(client: httpx.AsyncClient) -> None:
    # No override: this makes a real connection attempt to a closed port.
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "dependency_unavailable"
    assert error["message"] == "PostgreSQL is not reachable."
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert error["details"] == []


async def test_database_check_fails_when_query_exceeds_timeout() -> None:
    with pytest.raises(DependencyUnavailableError):
        await check_database(_HangingSession(), timeout_seconds=0.05)  # type: ignore[arg-type]
