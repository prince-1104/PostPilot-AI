"""Scheduled post creation, listing, updates, and cancellation."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    ForbiddenError,
    IdempotencyConflictError,
    InvalidStateError,
    NotFoundError,
    UnprocessableError,
    VersionConflictError,
)
from app.core.timezones import assert_offset_matches_timezone, require_iana_timezone
from app.models import LinkedInConnection, PublishAttempt, ScheduledPost, User
from app.models.enums import ConnectionStatus, PostStatus
from app.publishing.authorization import (
    apply_publish_approval,
    is_db_publish_approved,
    revoke_publish_approval,
)
from app.publishing.person_urn import linkedin_permalink_for_post_urn
from app.repositories.posts import PostRepository
from app.schemas.posts import (
    ApproveScheduledPost,
    CreateScheduledPost,
    PublishAttemptListResponse,
    PublishAttemptResponse,
    ScheduledPostListResponse,
    ScheduledPostResponse,
    UpdateScheduledPost,
)

logger = structlog.get_logger(__name__)

POSTING_SCOPE = "w_member_social"
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._\-]{8,128}$")


class PostService:
    def __init__(self, session: AsyncSession, *, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._repo = PostRepository(session)

    async def create(
        self,
        *,
        user: User,
        payload: CreateScheduledPost,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> ScheduledPostResponse:
        key = _validate_idempotency_key(idempotency_key)
        clock = now or datetime.now(UTC)
        self._validate_content(payload.content)
        require_iana_timezone(payload.timezone)
        assert_offset_matches_timezone(payload.scheduled_at, payload.timezone)
        self._validate_schedule_lead(payload.scheduled_at, clock=clock)

        connection = await self._require_schedulable_connection(
            user=user,
            connection_id=payload.linkedin_connection_id,
        )
        fingerprint = build_request_fingerprint(
            content=payload.content,
            scheduled_at=payload.scheduled_at,
            timezone=payload.timezone,
            linkedin_connection_id=payload.linkedin_connection_id,
        )

        existing = await self._repo.get_by_idempotency_key(user_id=user.id, idempotency_key=key)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise IdempotencyConflictError(
                    "Idempotency-Key was reused with a different request payload."
                )
            return self._to_response(existing, connection=connection, clock=clock)

        post = ScheduledPost(
            id=uuid4(),
            user_id=user.id,
            linkedin_connection_id=connection.id,
            content=payload.content,
            scheduled_at=payload.scheduled_at.astimezone(UTC),
            timezone=payload.timezone,
            status=PostStatus.SCHEDULED.value,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            version=1,
            linkedin_post_urn=None,
            created_at=clock,
            updated_at=clock,
            published_at=None,
        )
        # Approving user always comes from the authenticated session — never the client.
        apply_publish_approval(post, approved_by=user.id, clock=clock)

        dialect = self._db.get_bind().dialect.name
        if dialect == "postgresql":
            inserted_id = await self._repo.insert_ignoring_idempotency_conflict(post)
            await self._db.commit()
            stored = await self._resolve_idempotent_row(user_id=user.id, idempotency_key=key)
            if stored is None:
                raise IdempotencyConflictError(
                    "Could not resolve a concurrent create for this Idempotency-Key."
                )
            if stored.request_fingerprint != fingerprint:
                raise IdempotencyConflictError(
                    "Idempotency-Key was reused with a different request payload."
                )
            if inserted_id is not None:
                logger.info("posts.created", post_id=str(stored.id), user_id=str(user.id))
            return self._to_response(stored, connection=connection, clock=clock)

        # SQLite unit tests: catch the unique violation after commit.
        await self._repo.add(post)
        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            raced = await self._resolve_idempotent_row(user_id=user.id, idempotency_key=key)
            if raced is None:
                raise IdempotencyConflictError(
                    "Could not resolve a concurrent create for this Idempotency-Key."
                ) from exc
            if raced.request_fingerprint != fingerprint:
                raise IdempotencyConflictError(
                    "Idempotency-Key was reused with a different request payload."
                ) from None
            return self._to_response(raced, connection=connection, clock=clock)

        await self._db.refresh(post)
        logger.info("posts.created", post_id=str(post.id), user_id=str(user.id))
        return self._to_response(post, connection=connection, clock=clock)

    async def list_posts(
        self,
        *,
        user: User,
        status: str | None,
        scheduled_from: datetime | None,
        scheduled_to: datetime | None,
        cursor: str | None,
        limit: int | None,
        now: datetime | None = None,
    ) -> ScheduledPostListResponse:
        clock = now or datetime.now(UTC)
        page_size = limit or self._settings.posts_page_size_default
        page_size = min(max(page_size, 1), self._settings.posts_page_size_max)
        if status is not None and status not in {s.value for s in PostStatus}:
            raise UnprocessableError(f"Unknown status filter {status!r}.")
        if scheduled_from is not None and scheduled_from.tzinfo is None:
            raise UnprocessableError("scheduled_from must be timezone-aware.")
        if scheduled_to is not None and scheduled_to.tzinfo is None:
            raise UnprocessableError("scheduled_to must be timezone-aware.")

        cursor_scheduled_at, cursor_id = decode_cursor(cursor)
        rows = await self._repo.list_page(
            user_id=user.id,
            status=status,
            scheduled_from=scheduled_from.astimezone(UTC) if scheduled_from else None,
            scheduled_to=scheduled_to.astimezone(UTC) if scheduled_to else None,
            cursor_scheduled_at=cursor_scheduled_at,
            cursor_id=cursor_id,
            limit=page_size + 1,
        )
        connection = await self._get_user_connection(user.id)
        has_more = len(rows) > page_size
        page = rows[:page_size]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = encode_cursor(last.scheduled_at, last.id)
        return ScheduledPostListResponse(
            items=[self._to_response(row, connection=connection, clock=clock) for row in page],
            next_cursor=next_cursor,
        )

    async def get(
        self, *, user: User, post_id: UUID, now: datetime | None = None
    ) -> ScheduledPostResponse:
        clock = now or datetime.now(UTC)
        post = await self._repo.get_by_id_for_user(post_id=post_id, user_id=user.id)
        if post is None:
            raise NotFoundError("Post not found.")
        connection = await self._get_connection(post.linkedin_connection_id)
        return self._to_response(post, connection=connection, clock=clock)

    async def update(
        self,
        *,
        user: User,
        post_id: UUID,
        payload: UpdateScheduledPost,
        now: datetime | None = None,
    ) -> ScheduledPostResponse:
        clock = now or datetime.now(UTC)
        post = await self._repo.get_by_id_for_user(post_id=post_id, user_id=user.id)
        if post is None:
            raise NotFoundError("Post not found.")
        if post.status != PostStatus.SCHEDULED.value:
            raise InvalidStateError("Only posts in 'scheduled' status can be edited.")
        if post.version != payload.expected_version:
            raise VersionConflictError(
                "The post was modified by another request. Refresh and try again."
            )

        new_content = payload.content if payload.content is not None else post.content
        new_scheduled = (
            payload.scheduled_at if payload.scheduled_at is not None else post.scheduled_at
        )
        new_timezone = payload.timezone if payload.timezone is not None else post.timezone

        if payload.content is not None:
            self._validate_content(new_content)
        require_iana_timezone(new_timezone)
        if payload.scheduled_at is not None or payload.timezone is not None:
            # Re-validate wall-clock consistency only when schedule fields change.
            assert_offset_matches_timezone(new_scheduled, new_timezone)
        if payload.scheduled_at is not None:
            self._validate_schedule_lead(new_scheduled, clock=clock)

        connection = await self._require_schedulable_connection(
            user=user,
            connection_id=post.linkedin_connection_id,
        )

        material_change = (
            new_content != post.content
            or new_scheduled.astimezone(UTC) != post.scheduled_at.astimezone(UTC)
            or new_timezone != post.timezone
        )
        if material_change and payload.confirm_publish is not True:
            raise UnprocessableError(
                "Editing content, destination time, or timezone requires confirm_publish=true "
                "to renew LinkedIn publishing approval."
            )

        # Apply field updates first; version bumps inside update_if_version.
        updated = await self._repo.update_if_version(
            post=post,
            expected_version=payload.expected_version,
            content=new_content,
            scheduled_at=new_scheduled.astimezone(UTC),
            timezone=new_timezone,
            updated_at=clock,
        )
        if updated is None:
            # State or version changed under us.
            await self._db.refresh(post)
            if post.status != PostStatus.SCHEDULED.value:
                raise InvalidStateError("Only posts in 'scheduled' status can be edited.")
            raise VersionConflictError(
                "The post was modified by another request. Refresh and try again."
            )

        if material_change:
            apply_publish_approval(updated, approved_by=user.id, clock=clock)
        await self._db.commit()
        await self._db.refresh(updated)
        logger.info("posts.updated", post_id=str(updated.id), user_id=str(user.id))
        return self._to_response(updated, connection=connection, clock=clock)

    async def approve(
        self,
        *,
        user: User,
        post_id: UUID,
        payload: ApproveScheduledPost,
        now: datetime | None = None,
    ) -> ScheduledPostResponse:
        """Approve an existing scheduled post owned by the session user."""
        clock = now or datetime.now(UTC)
        post = await self._repo.get_by_id_for_user(post_id=post_id, user_id=user.id)
        if post is None:
            raise NotFoundError("Post not found.")
        if post.status != PostStatus.SCHEDULED.value:
            raise InvalidStateError("Only posts in 'scheduled' status can be approved.")
        if post.version != payload.expected_version:
            raise VersionConflictError(
                "The post was modified by another request. Refresh and try again."
            )

        connection = await self._require_schedulable_connection(
            user=user,
            connection_id=post.linkedin_connection_id,
        )
        updated = await self._repo.update_if_version(
            post=post,
            expected_version=payload.expected_version,
            updated_at=clock,
        )
        if updated is None:
            await self._db.refresh(post)
            if post.status != PostStatus.SCHEDULED.value:
                raise InvalidStateError("Only posts in 'scheduled' status can be approved.")
            raise VersionConflictError(
                "The post was modified by another request. Refresh and try again."
            )
        apply_publish_approval(updated, approved_by=user.id, clock=clock)
        await self._db.commit()
        await self._db.refresh(updated)
        logger.info("posts.publish_approved", post_id=str(updated.id), user_id=str(user.id))
        return self._to_response(updated, connection=connection, clock=clock)

    async def cancel(
        self,
        *,
        user: User,
        post_id: UUID,
        expected_version: int,
        now: datetime | None = None,
    ) -> ScheduledPostResponse:
        clock = now or datetime.now(UTC)
        post = await self._repo.get_by_id_for_user(post_id=post_id, user_id=user.id)
        if post is None:
            raise NotFoundError("Post not found.")

        connection = await self._get_connection(post.linkedin_connection_id)

        # Idempotent repeated cancel of an already-cancelled post.
        if post.status == PostStatus.CANCELLED.value:
            return self._to_response(post, connection=connection, clock=clock)

        if post.status == PostStatus.PROCESSING.value:
            raise InvalidStateError(
                "This post is already processing. Cancellation can no longer be guaranteed "
                "if LinkedIn submission has started."
            )
        if post.status != PostStatus.SCHEDULED.value:
            raise InvalidStateError(
                "Only posts in 'scheduled' status can be cancelled."
            )
        if post.version != expected_version:
            raise VersionConflictError(
                "The post was modified by another request. Refresh and try again."
            )

        revoke_publish_approval(post, clock=clock)
        updated = await self._repo.update_if_version(
            post=post,
            expected_version=expected_version,
            status=PostStatus.CANCELLED.value,
            updated_at=clock,
            approval_revoked_at=post.approval_revoked_at,
            publish_approved_at=post.publish_approved_at,
            publish_approved_by=post.publish_approved_by,
            approved_content_hash=post.approved_content_hash,
            approved_version=post.approved_version,
            # Cancel must not leave a misleading retry schedule in the UI.
            next_attempt_at=None,
            dispatch_lease_until=None,
            processing_lease_until=None,
            current_attempt_id=None,
        )
        if updated is None:
            await self._db.refresh(post)
            if post.status == PostStatus.CANCELLED.value:
                return self._to_response(post, connection=connection, clock=clock)
            if post.status == PostStatus.PROCESSING.value:
                raise InvalidStateError(
                    "This post is already processing. Cancellation can no longer be guaranteed "
                    "if LinkedIn submission has started."
                )
            if post.status != PostStatus.SCHEDULED.value:
                raise InvalidStateError(
                    "Only posts in 'scheduled' status can be cancelled."
                )
            raise VersionConflictError(
                "The post was modified by another request. Refresh and try again."
            )

        await self._db.commit()
        await self._db.refresh(updated)
        logger.info("posts.cancelled", post_id=str(updated.id), user_id=str(user.id))
        return self._to_response(updated, connection=connection, clock=clock)

    async def validate_schedule_inputs(
        self,
        *,
        user: User,
        content: str,
        scheduled_at: datetime,
        timezone: str,
        linkedin_connection_id: UUID,
        now: datetime | None = None,
    ) -> tuple[LinkedInConnection, list[str]]:
        """Read-only create validation used by assistant schedule preview (no inserts)."""
        clock = now or datetime.now(UTC)
        self._validate_content(content)
        require_iana_timezone(timezone)
        assert_offset_matches_timezone(scheduled_at, timezone)
        self._validate_schedule_lead(scheduled_at, clock=clock)
        connection = await self._require_schedulable_connection(
            user=user, connection_id=linkedin_connection_id
        )
        warnings: list[str] = []
        if connection.token_expires_at is not None:
            token_exp = connection.token_expires_at
            if token_exp.tzinfo is None:
                token_exp = token_exp.replace(tzinfo=UTC)
            if token_exp < scheduled_at.astimezone(UTC):
                warnings.append(
                    "The LinkedIn access token expires before this post is scheduled to publish. "
                    "Reconnect LinkedIn before the scheduled time."
                )
        return connection, warnings

    def _validate_content(self, content: str) -> None:
        max_len = self._settings.post_content_max_length
        if len(content) > max_len:
            raise UnprocessableError(
                f"content must be at most {max_len} characters "
                "(LinkedIn UGC/share commentary limit)."
            )

    def _validate_schedule_lead(self, scheduled_at: datetime, *, clock: datetime) -> None:
        lead = timedelta(seconds=self._settings.schedule_min_lead_seconds)
        earliest = clock.astimezone(UTC) + lead
        if scheduled_at.astimezone(UTC) < earliest:
            raise UnprocessableError(
                f"scheduled_at must be at least {self._settings.schedule_min_lead_seconds} "
                "seconds in the future."
            )

    async def _require_schedulable_connection(
        self, *, user: User, connection_id: UUID
    ) -> LinkedInConnection:
        connection = await self._get_connection(connection_id)
        if connection is None or connection.user_id != user.id:
            raise ForbiddenError("LinkedIn connection not found for this account.")
        if connection.connection_status != ConnectionStatus.CONNECTED.value:
            raise ForbiddenError("LinkedIn connection is not active. Reconnect and try again.")
        if not connection.encrypted_access_token:
            raise ForbiddenError("LinkedIn connection has no stored access token. Reconnect.")
        scopes = {part for part in connection.granted_scopes.replace(",", " ").split() if part}
        if POSTING_SCOPE not in scopes:
            raise ForbiddenError(
                f"LinkedIn connection is missing the '{POSTING_SCOPE}' permission required "
                "to schedule posts."
            )
        return connection

    async def _get_connection(self, connection_id: UUID) -> LinkedInConnection | None:
        result = await self._db.execute(
            select(LinkedInConnection).where(LinkedInConnection.id == connection_id)
        )
        return result.scalar_one_or_none()

    async def _resolve_idempotent_row(
        self, *, user_id: UUID, idempotency_key: str
    ) -> ScheduledPost | None:
        """Load the winning row after a unique-constraint race (briefly retry)."""
        for attempt in range(8):
            raced = await self._repo.get_by_idempotency_key(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if raced is not None:
                return raced
            await asyncio.sleep(0.025 * (attempt + 1))
        return None

    async def _get_user_connection(self, user_id: UUID) -> LinkedInConnection | None:
        result = await self._db.execute(
            select(LinkedInConnection).where(LinkedInConnection.user_id == user_id)
        )
        return result.scalar_one_or_none()

    def _to_response(
        self,
        post: ScheduledPost,
        *,
        connection: LinkedInConnection | None,
        clock: datetime,
    ) -> ScheduledPostResponse:
        expires_before = False
        warning: str | None = None
        if connection is not None and connection.token_expires_at is not None:
            token_exp = connection.token_expires_at
            if token_exp.tzinfo is None:
                token_exp = token_exp.replace(tzinfo=UTC)
            if token_exp < post.scheduled_at.astimezone(UTC):
                expires_before = True
                warning = (
                    "The LinkedIn access token expires before this post is scheduled to publish. "
                    "Reconnect LinkedIn before the scheduled time. PostPilot cannot refresh "
                    "LinkedIn tokens automatically."
                )
        urn = post.linkedin_post_urn
        simulated = bool(urn and urn.startswith("urn:li:share:fake-"))
        reconnect = bool(
            post.last_error_code
            in {
                "linkedin_unauthorized",
                "linkedin_token_expired",
                "connection_not_active",
                "missing_access_token",
                "missing_w_member_social",
                "linkedin_forbidden",
            }
        )
        approved = is_db_publish_approved(post)
        # Only surface retry timing for posts that may still execute.
        next_attempt = (
            post.next_attempt_at
            if post.status in {PostStatus.SCHEDULED.value, PostStatus.PROCESSING.value}
            else None
        )
        return ScheduledPostResponse(
            id=post.id,
            linkedin_connection_id=post.linkedin_connection_id,
            content=post.content,
            scheduled_at=post.scheduled_at,
            timezone=post.timezone,
            status=post.status,
            version=post.version,
            created_at=post.created_at,
            updated_at=post.updated_at,
            published_at=post.published_at,
            linkedin_post_urn=urn,
            attempt_count=post.attempt_count,
            next_attempt_at=next_attempt,
            last_error_code=post.last_error_code,
            last_error_at=post.last_error_at,
            publication_simulated=simulated,
            linkedin_permalink=(
                None if simulated or not urn else linkedin_permalink_for_post_urn(urn)
            ),
            connection_expires_before_schedule=expires_before,
            connection_expiry_warning=warning,
            reconnect_required=reconnect,
            publish_approved=approved,
            publish_approved_at=post.publish_approved_at,
            publish_approved_by=post.publish_approved_by,
            approval_revoked_at=post.approval_revoked_at,
        )

    async def list_attempts(
        self, *, user: User, post_id: UUID
    ) -> PublishAttemptListResponse:
        post = await self._repo.get_by_id_for_user(post_id=post_id, user_id=user.id)
        if post is None:
            raise NotFoundError("Post not found.")
        result = await self._db.execute(
            select(PublishAttempt)
            .where(PublishAttempt.post_id == post.id)
            .order_by(PublishAttempt.attempt_number.asc())
        )
        rows = list(result.scalars().all())
        return PublishAttemptListResponse(
            items=[
                PublishAttemptResponse(
                    id=row.id,
                    attempt_number=row.attempt_number,
                    execution_state=row.execution_state,
                    started_at=row.started_at,
                    request_started_at=row.request_started_at,
                    finished_at=row.finished_at,
                    provider_http_status=row.provider_http_status,
                    error_category=row.error_category,
                    sanitized_error_code=row.sanitized_error_code,
                    next_retry_at=row.next_retry_at,
                    provider_post_urn=row.provider_post_urn,
                    publication_simulated=bool(
                        row.provider_post_urn
                        and row.provider_post_urn.startswith("urn:li:share:fake-")
                    ),
                )
                for row in rows
            ]
        )


def build_request_fingerprint(
    *,
    content: str,
    scheduled_at: datetime,
    timezone: str,
    linkedin_connection_id: UUID,
) -> str:
    normalized = {
        "content": content,
        "scheduled_at": scheduled_at.astimezone(UTC).isoformat(),
        "timezone": timezone,
        "linkedin_connection_id": str(linkedin_connection_id),
    }
    payload = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_idempotency_key(value: str) -> str:
    key = value.strip()
    if not _IDEMPOTENCY_KEY_RE.fullmatch(key):
        raise UnprocessableError(
            "Idempotency-Key must be 8-128 characters of letters, digits, '.', '_' or '-'."
        )
    return key


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def encode_cursor(scheduled_at: datetime, post_id: UUID) -> str:
    raw = f"{_as_utc(scheduled_at).isoformat()}|{post_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str | None) -> tuple[datetime | None, UUID | None]:
    if not cursor:
        return None, None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        stamp, post_id = raw.split("|", 1)
        return _as_utc(datetime.fromisoformat(stamp)), UUID(post_id)
    except Exception as exc:
        raise UnprocessableError("Invalid pagination cursor.") from exc
