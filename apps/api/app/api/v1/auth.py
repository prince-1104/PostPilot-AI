"""Authentication and LinkedIn OAuth routes."""

import structlog
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.api.deps import (
    CurrentUserDep,
    EncryptorDep,
    LinkedInClientDep,
    OidcValidatorDep,
    RequireOriginDep,
    SessionDep,
    SettingsDep,
)
from app.core.cookies import (
    OAUTH_NONCE_COOKIE,
    SESSION_COOKIE,
    clear_oauth_nonce_cookie,
    clear_session_cookie,
    set_oauth_nonce_cookie,
    set_session_cookie,
)
from app.core.errors import AppError
from app.schemas.auth import UserProfileResponse
from app.services.connections import user_to_profile
from app.services.oauth import OAuthService, frontend_redirect
from app.services.sessions import SessionService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/linkedin")
async def linkedin_authorize(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    linkedin: LinkedInClientDep,
    oidc: OidcValidatorDep,
    encryptor: EncryptorDep,
) -> RedirectResponse:
    """Start LinkedIn OAuth: persist hashed state/nonce, set cookie, redirect."""
    service = OAuthService(
        session,
        settings=settings,
        linkedin=linkedin,
        oidc=oidc,
        encryptor=encryptor,
    )
    start = await service.start(
        existing_session_token=request.cookies.get(SESSION_COOKIE),
    )
    redirect = RedirectResponse(url=start.authorization_url, status_code=302)
    set_oauth_nonce_cookie(
        redirect,
        nonce=start.browser_nonce,
        max_age=settings.oauth_state_ttl_seconds,
        secure=settings.cookie_secure,
    )
    return redirect


@router.get("/linkedin/callback")
async def linkedin_callback(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    linkedin: LinkedInClientDep,
    oidc: OidcValidatorDep,
    encryptor: EncryptorDep,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None, alias="error_description"),
) -> RedirectResponse:
    """Complete LinkedIn OAuth and redirect to the frontend connections page."""
    service = OAuthService(
        session,
        settings=settings,
        linkedin=linkedin,
        oidc=oidc,
        encryptor=encryptor,
    )
    try:
        result = await service.complete(
            code=code,
            state=state,
            browser_nonce=request.cookies.get(OAUTH_NONCE_COOKIE),
            error=error,
            error_description=error_description,
            current_session_token=request.cookies.get(SESSION_COOKIE),
        )
    except AppError as exc:
        # Browser callback: always redirect with a safe reason, never JSON.
        logger.warning("oauth.callback_failed", code=exc.code)
        redirect = RedirectResponse(
            url=frontend_redirect(
                settings.web_base_url,
                path="/connections",
                params={"oauth": "error", "reason": exc.message},
            ),
            status_code=302,
        )
        clear_oauth_nonce_cookie(redirect, secure=settings.cookie_secure)
        return redirect
    except Exception:
        logger.exception("oauth.callback_unhandled")
        redirect = RedirectResponse(
            url=frontend_redirect(
                settings.web_base_url,
                path="/connections",
                params={
                    "oauth": "error",
                    "reason": "LinkedIn connection failed unexpectedly.",
                },
            ),
            status_code=302,
        )
        clear_oauth_nonce_cookie(redirect, secure=settings.cookie_secure)
        return redirect

    redirect = RedirectResponse(
        url=frontend_redirect(
            settings.web_base_url,
            path="/connections",
            params={"oauth": "success"},
        ),
        status_code=302,
    )
    set_session_cookie(
        redirect,
        token=result.issued_session.raw_token,
        max_age=settings.session_ttl_seconds,
        secure=settings.cookie_secure,
    )
    clear_oauth_nonce_cookie(redirect, secure=settings.cookie_secure)
    return redirect


@router.get("/me", response_model=UserProfileResponse)
async def auth_me(user: CurrentUserDep) -> UserProfileResponse:
    return user_to_profile(user)


@router.post("/logout", status_code=204)
async def auth_logout(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    _: RequireOriginDep,
) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await SessionService(session, ttl_seconds=settings.session_ttl_seconds).revoke_token(token)
        await session.commit()
    clear_session_cookie(response, secure=settings.cookie_secure)
    response.status_code = 204
    return response
