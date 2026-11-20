"""FastAPI dependencies shared across routers."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.cookies import SESSION_COOKIE
from app.core.errors import OriginRejectedError, UnauthorizedError
from app.core.security import TokenEncryptor
from app.integrations.linkedin import HttpLinkedInClient, LinkedInOidcValidator
from app.models import User
from app.services.sessions import SessionService


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session that is closed when the request ends."""
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_encryptor(request: Request) -> TokenEncryptor:
    encryptor: TokenEncryptor = request.app.state.token_encryptor
    return encryptor


def get_linkedin_client(request: Request) -> HttpLinkedInClient:
    client: HttpLinkedInClient = request.app.state.linkedin_client
    return client


def get_oidc_validator(request: Request) -> LinkedInOidcValidator:
    validator: LinkedInOidcValidator = request.app.state.oidc_validator
    return validator


EncryptorDep = Annotated[TokenEncryptor, Depends(get_encryptor)]
LinkedInClientDep = Annotated[HttpLinkedInClient, Depends(get_linkedin_client)]
OidcValidatorDep = Annotated[LinkedInOidcValidator, Depends(get_oidc_validator)]


async def get_current_user(request: Request, session: SessionDep, settings: SettingsDep) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise UnauthorizedError("Authentication required.")
    user = await SessionService(
        session, ttl_seconds=settings.session_ttl_seconds
    ).get_user_for_token(token)
    if user is None:
        raise UnauthorizedError("Authentication required.")
    return user


async def get_optional_user(
    request: Request, session: SessionDep, settings: SettingsDep
) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await SessionService(
        session, ttl_seconds=settings.session_ttl_seconds
    ).get_user_for_token(token)


CurrentUserDep = Annotated[User, Depends(get_current_user)]
OptionalUserDep = Annotated[User | None, Depends(get_optional_user)]


def require_browser_origin(request: Request, settings: SettingsDep) -> None:
    """Reject state-changing browser requests whose Origin is not allow-listed."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin is None:
        # Non-browser clients (curl, server-to-server) may omit Origin.
        return
    if origin not in settings.cors_allowed_origins:
        raise OriginRejectedError("Request Origin is not allowed.")


RequireOriginDep = Annotated[None, Depends(require_browser_origin)]
