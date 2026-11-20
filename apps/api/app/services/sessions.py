"""Server-side opaque session creation, lookup, rotation, and revocation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import generate_opaque_token, hash_token
from app.models import AuthSession, User


@dataclass(frozen=True, slots=True)
class IssuedSession:
    session: AuthSession
    raw_token: str


def _as_utc(value: datetime) -> datetime:
    """Normalize DB datetimes so SQLite (naive) and PostgreSQL (aware) compare safely."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SessionService:
    def __init__(self, session: AsyncSession, *, ttl_seconds: int) -> None:
        self._db = session
        self._ttl = ttl_seconds

    async def create_session(self, user_id: UUID) -> IssuedSession:
        raw_token = generate_opaque_token()
        now = datetime.now(UTC)
        row = AuthSession(
            id=uuid4(),
            user_id=user_id,
            session_token_hash=hash_token(raw_token),
            expires_at=now + timedelta(seconds=self._ttl),
            revoked_at=None,
            created_at=now,
        )
        self._db.add(row)
        await self._db.flush()
        return IssuedSession(session=row, raw_token=raw_token)

    async def rotate_session(self, *, user_id: UUID, previous_token: str | None) -> IssuedSession:
        if previous_token:
            await self.revoke_token(previous_token)
        return await self.create_session(user_id)

    async def revoke_token(self, raw_token: str) -> bool:
        now = datetime.now(UTC)
        result = await self._db.execute(
            update(AuthSession)
            .where(
                AuthSession.session_token_hash == hash_token(raw_token),
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
            .returning(AuthSession.id)
        )
        return result.scalar_one_or_none() is not None

    async def get_user_for_token(self, raw_token: str) -> User | None:
        now = datetime.now(UTC)
        result = await self._db.execute(
            select(AuthSession)
            .where(AuthSession.session_token_hash == hash_token(raw_token))
            .options(selectinload(AuthSession.user).selectinload(User.linkedin_connection))
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        if row.revoked_at is not None:
            return None
        if _as_utc(row.expires_at) <= now:
            return None
        return row.user
