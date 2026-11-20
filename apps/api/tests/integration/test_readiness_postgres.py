"""Readiness against a real PostgreSQL instance.

Excluded from the default test run. Requires the POSTGRES_* variables to point at a
reachable database:

    uv run --env-file ../../.env pytest -m integration
"""

from collections.abc import AsyncIterator

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
async def live_client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def test_ready_returns_ready_when_postgres_is_reachable(
    live_client: httpx.AsyncClient,
) -> None:
    response = await live_client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}
