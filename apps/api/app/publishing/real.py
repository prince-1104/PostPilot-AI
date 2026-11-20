"""Real LinkedIn Posts API publisher (Phase 4B).

Never logs tokens or authorization headers. HTTP POST retries are disabled.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.core.config import Settings
from app.core.security import TokenEncryptionError, TokenEncryptor
from app.models import LinkedInConnection
from app.models.enums import ConnectionStatus
from app.publishing.outcomes import (
    OutcomeKind,
    PublishExecutionContext,
    PublishOutcome,
)
from app.publishing.person_urn import (
    PersonUrnError,
    person_urn_from_oidc_subject,
    validate_post_urn,
)

logger = structlog.get_logger(__name__)

POSTING_SCOPE = "w_member_social"


class RealLinkedInPublisher:
    """Publishes text-only posts via ``POST /rest/posts``."""

    def __init__(
        self,
        *,
        settings: Settings,
        encryptor: TokenEncryptor,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not settings.enable_real_publishing:
            raise RuntimeError(
                "Real LinkedIn publishing requires ENABLE_REAL_PUBLISHING=true."
            )
        self._settings = settings
        self._encryptor = encryptor
        self._owns_client = http_client is None
        timeout = httpx.Timeout(
            connect=settings.linkedin_publish_connect_timeout_seconds,
            read=settings.linkedin_publish_read_timeout_seconds,
            write=settings.linkedin_publish_write_timeout_seconds,
            pool=settings.linkedin_publish_pool_timeout_seconds,
        )
        self._client = http_client or httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            # Critical: never auto-retry non-idempotent POSTs.
            transport=httpx.HTTPTransport(retries=0),
        )
        self.requests_made: list[dict[str, Any]] = []

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def publish_text_post(
        self,
        *,
        connection: LinkedInConnection,
        content: str,
        execution_context: PublishExecutionContext,
    ) -> PublishOutcome:
        precheck = self._preflight(connection)
        if precheck is not None:
            return precheck

        try:
            author = person_urn_from_oidc_subject(connection.provider_subject)
        except PersonUrnError:
            return PublishOutcome(
                kind=OutcomeKind.PERMANENT,
                submission_started=False,
                error_category="identity",
                sanitized_error_code="invalid_person_urn",
                simulated=False,
            )

        try:
            access_token = self._encryptor.decrypt(connection.encrypted_access_token or "")
        except TokenEncryptionError:
            logger.warning(
                "linkedin.publish.decrypt_failed",
                post_id=execution_context.post_id,
                attempt_id=execution_context.attempt_id,
            )
            return PublishOutcome(
                kind=OutcomeKind.PERMANENT,
                submission_started=False,
                error_category="crypto",
                sanitized_error_code="token_decrypt_failed",
                simulated=False,
            )

        url = f"{self._settings.linkedin_api_base_url.rstrip('/')}/rest/posts"
        payload = {
            "author": author,
            "commentary": content,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "Linkedin-Version": self._settings.linkedin_api_version,
        }

        # Drop the plaintext token from local scope as soon as headers are built.
        del access_token

        self.requests_made.append(
            {
                "method": "POST",
                "path": "/rest/posts",
                "author": author,
                "attempt_id": execution_context.attempt_id,
            }
        )
        logger.info(
            "linkedin.publish.request",
            post_id=execution_context.post_id,
            attempt_id=execution_context.attempt_id,
            author_urn=author,
            api_version=self._settings.linkedin_api_version,
        )

        try:
            response = self._client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            return PublishOutcome(
                kind=OutcomeKind.AMBIGUOUS,
                submission_started=True,
                error_category="timeout",
                sanitized_error_code="linkedin_publish_timeout",
                simulated=False,
            )
        except httpx.TransportError:
            return PublishOutcome(
                kind=OutcomeKind.AMBIGUOUS,
                submission_started=True,
                error_category="network",
                sanitized_error_code="linkedin_publish_transport_error",
                simulated=False,
            )
        finally:
            # Ensure headers dict does not linger with a bearer token.
            headers.pop("Authorization", None)

        return self._classify_response(response)

    def _preflight(self, connection: LinkedInConnection) -> PublishOutcome | None:
        if connection.connection_status != ConnectionStatus.CONNECTED.value:
            return PublishOutcome(
                kind=OutcomeKind.CONNECTION_EXPIRED,
                submission_started=False,
                http_status=401,
                error_category="auth",
                sanitized_error_code="connection_not_active",
                simulated=False,
            )
        if not connection.encrypted_access_token:
            return PublishOutcome(
                kind=OutcomeKind.CONNECTION_EXPIRED,
                submission_started=False,
                http_status=401,
                error_category="auth",
                sanitized_error_code="missing_access_token",
                simulated=False,
            )
        scopes = {
            part for part in connection.granted_scopes.replace(",", " ").split() if part
        }
        if POSTING_SCOPE not in scopes:
            return PublishOutcome(
                kind=OutcomeKind.PERMANENT,
                submission_started=False,
                http_status=403,
                error_category="auth",
                sanitized_error_code="missing_w_member_social",
                simulated=False,
            )
        if connection.token_expires_at is not None:
            expires = connection.token_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires <= datetime.now(UTC):
                return PublishOutcome(
                    kind=OutcomeKind.CONNECTION_EXPIRED,
                    submission_started=False,
                    http_status=401,
                    error_category="auth",
                    sanitized_error_code="linkedin_token_expired",
                    simulated=False,
                )
        return None

    def _classify_response(self, response: httpx.Response) -> PublishOutcome:
        status = response.status_code
        if status == 201:
            raw_id = response.headers.get("x-restli-id") or response.headers.get("X-RestLi-Id")
            if not raw_id:
                return PublishOutcome(
                    kind=OutcomeKind.AMBIGUOUS,
                    submission_started=True,
                    http_status=201,
                    error_category="provider",
                    sanitized_error_code="linkedin_201_missing_post_urn",
                    simulated=False,
                )
            try:
                urn = validate_post_urn(raw_id)
            except ValueError:
                return PublishOutcome(
                    kind=OutcomeKind.AMBIGUOUS,
                    submission_started=True,
                    http_status=201,
                    error_category="provider",
                    sanitized_error_code="linkedin_201_malformed_post_urn",
                    simulated=False,
                )
            return PublishOutcome(
                kind=OutcomeKind.SUCCESS,
                submission_started=True,
                provider_post_urn=urn,
                http_status=201,
                simulated=False,
            )

        if status in {401}:
            return PublishOutcome(
                kind=OutcomeKind.CONNECTION_EXPIRED,
                submission_started=True,
                http_status=status,
                error_category="auth",
                sanitized_error_code="linkedin_unauthorized",
                simulated=False,
            )
        if status == 403:
            return PublishOutcome(
                kind=OutcomeKind.PERMANENT,
                submission_started=True,
                http_status=status,
                error_category="auth",
                sanitized_error_code="linkedin_forbidden",
                simulated=False,
            )
        if status in {400, 422}:
            return PublishOutcome(
                kind=OutcomeKind.PERMANENT,
                submission_started=True,
                http_status=status,
                error_category="validation",
                sanitized_error_code="linkedin_validation_rejected",
                simulated=False,
            )
        if status == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            return PublishOutcome(
                kind=OutcomeKind.RETRYABLE,
                submission_started=True,
                http_status=429,
                error_category="rate_limit",
                sanitized_error_code="linkedin_rate_limited",
                retry_after_seconds=retry_after,
                simulated=False,
            )
        if status >= 500:
            return PublishOutcome(
                kind=OutcomeKind.AMBIGUOUS,
                submission_started=True,
                http_status=status,
                error_category="provider_5xx",
                sanitized_error_code="linkedin_server_error",
                simulated=False,
            )
        return PublishOutcome(
            kind=OutcomeKind.AMBIGUOUS,
            submission_started=True,
            http_status=status,
            error_category="provider",
            sanitized_error_code="linkedin_unexpected_response",
            simulated=False,
        )


def _parse_retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        seconds = int(value.strip())
    except ValueError:
        return None
    if seconds < 0:
        return None
    return min(seconds, 86_400)


