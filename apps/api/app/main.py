"""FastAPI application factory.

Run with: `uvicorn app.main:create_app --factory`
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.security import TokenEncryptor
from app.db.session import create_engine, create_session_factory
from app.integrations.linkedin import HttpLinkedInClient, LinkedInOidcValidator

logger = structlog.get_logger(__name__)

API_V1_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass explicit settings; servers read the environment."""
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)

    # Fail fast on an unusable encryption key before accepting traffic.
    token_encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.session_factory = create_session_factory(engine)
        linkedin_client = HttpLinkedInClient(settings)
        app.state.linkedin_client = linkedin_client
        app.state.oidc_validator = LinkedInOidcValidator(client_id=settings.linkedin_client_id)
        app.state.token_encryptor = token_encryptor
        logger.info("app.started", app_env=settings.app_env)
        try:
            yield
        finally:
            await linkedin_client.aclose()
            await engine.dispose()
            logger.info("app.stopped")

    # Interactive API docs are a development aid and stay off in production.
    docs_enabled = settings.app_env != "production"
    app = FastAPI(
        title="PostPilot AI API",
        lifespan=lifespan,
        openapi_url=f"{API_V1_PREFIX}/openapi.json" if docs_enabled else None,
        docs_url=f"{API_V1_PREFIX}/docs" if docs_enabled else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.token_encryptor = token_encryptor

    # Middleware added last runs first. CORS must be outermost so that every
    # response, including error responses produced by RequestContextMiddleware,
    # carries the CORS headers browsers need in order to read it.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # Explicit origins only: settings validation rejects wildcards, which must
        # never be combined with credentialed requests.
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    register_exception_handlers(app)
    app.include_router(v1_router, prefix=API_V1_PREFIX)
    return app
