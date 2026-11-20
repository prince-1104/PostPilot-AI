"""Focused persistence helpers for scheduled posts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ScheduledPost
from app.models.enums import PostStatus


class PostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def get_by_id_for_user(self, *, post_id: UUID, user_id: UUID) -> ScheduledPost | None:
        result = await self._db.execute(
            select(ScheduledPost).where(
                ScheduledPost.id == post_id,
                ScheduledPost.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self, *, user_id: UUID, idempotency_key: str
    ) -> ScheduledPost | None:
        result = await self._db.execute(
            select(ScheduledPost).where(
                ScheduledPost.user_id == user_id,
                ScheduledPost.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def add(self, post: ScheduledPost) -> ScheduledPost:
        # Do not flush here: concurrent unique violations must surface on commit
        # so the service can catch IntegrityError and return the winning row.
        self._db.add(post)
        return post

    async def insert_ignoring_idempotency_conflict(self, post: ScheduledPost) -> UUID | None:
        """Insert a row; return its id, or None when (user_id, idempotency_key) already exists.

        Uses PostgreSQL ``ON CONFLICT DO NOTHING`` so concurrent duplicates do not raise
        IntegrityError (which can poison asyncpg connections under asyncio gather).
        """
        stmt = (
            pg_insert(ScheduledPost)
            .values(
                id=post.id,
                user_id=post.user_id,
                linkedin_connection_id=post.linkedin_connection_id,
                content=post.content,
                scheduled_at=post.scheduled_at,
                timezone=post.timezone,
                status=post.status,
                idempotency_key=post.idempotency_key,
                request_fingerprint=post.request_fingerprint,
                version=post.version,
                linkedin_post_urn=post.linkedin_post_urn,
                created_at=post.created_at,
                updated_at=post.updated_at,
                published_at=post.published_at,
            )
            .on_conflict_do_nothing(constraint="uq_scheduled_posts_user_id_idempotency_key")
            .returning(ScheduledPost.id)
        )
        result = await self._db.execute(stmt)
        row = result.first()
        return row[0] if row is not None else None

    def list_query(
        self,
        *,
        user_id: UUID,
        status: str | None,
        scheduled_from: datetime | None,
        scheduled_to: datetime | None,
        cursor_scheduled_at: datetime | None,
        cursor_id: UUID | None,
    ) -> Select[tuple[ScheduledPost]]:
        filters = [ScheduledPost.user_id == user_id]
        if status is not None:
            filters.append(ScheduledPost.status == status)
        if scheduled_from is not None:
            filters.append(ScheduledPost.scheduled_at >= scheduled_from)
        if scheduled_to is not None:
            filters.append(ScheduledPost.scheduled_at <= scheduled_to)
        if cursor_scheduled_at is not None and cursor_id is not None:
            cursor_at = self._normalize_for_dialect(cursor_scheduled_at)
            # Stable descending order: (scheduled_at DESC, id DESC).
            filters.append(
                or_(
                    ScheduledPost.scheduled_at < cursor_at,
                    and_(
                        ScheduledPost.scheduled_at == cursor_at,
                        ScheduledPost.id < cursor_id,
                    ),
                )
            )
        return (
            select(ScheduledPost)
            .where(*filters)
            .order_by(ScheduledPost.scheduled_at.desc(), ScheduledPost.id.desc())
        )

    async def list_page(
        self,
        *,
        user_id: UUID,
        status: str | None,
        scheduled_from: datetime | None,
        scheduled_to: datetime | None,
        cursor_scheduled_at: datetime | None,
        cursor_id: UUID | None,
        limit: int,
    ) -> list[ScheduledPost]:
        stmt = self.list_query(
            user_id=user_id,
            status=status,
            scheduled_from=(
                self._normalize_for_dialect(scheduled_from) if scheduled_from else None
            ),
            scheduled_to=self._normalize_for_dialect(scheduled_to) if scheduled_to else None,
            cursor_scheduled_at=cursor_scheduled_at,
            cursor_id=cursor_id,
        ).limit(limit)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    def _normalize_for_dialect(self, value: datetime) -> datetime:
        """SQLite returns/compares naive timestamps; PostgreSQL uses timestamptz."""
        utc = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
        bind = self._db.get_bind()
        if bind.dialect.name == "sqlite":
            return utc.replace(tzinfo=None)
        return utc

    async def update_if_version(
        self,
        *,
        post: ScheduledPost,
        expected_version: int,
        **fields: object,
    ) -> ScheduledPost | None:
        """Apply fields when version matches; returns None on stale version."""
        if post.version != expected_version:
            return None
        if post.status != PostStatus.SCHEDULED.value:
            return None
        for key, value in fields.items():
            setattr(post, key, value)
        post.version = expected_version + 1
        await self._db.flush()
        return post
