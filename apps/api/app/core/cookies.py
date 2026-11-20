"""Cookie names and helpers for auth and OAuth CSRF bindings."""

from fastapi import Response

SESSION_COOKIE = "postpilot_session"
OAUTH_NONCE_COOKIE = "postpilot_oauth_nonce"


def set_session_cookie(
    response: Response,
    *,
    token: str,
    max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def set_oauth_nonce_cookie(
    response: Response,
    *,
    nonce: str,
    max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        key=OAUTH_NONCE_COOKIE,
        value=nonce,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_oauth_nonce_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        key=OAUTH_NONCE_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )
