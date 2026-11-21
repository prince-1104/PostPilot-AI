"""User-authored LinkedIn posts scheduled for later publication."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import PostStatus


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_scheduled_posts_user_id_idempotency_key",
        ),
        Index("ix_scheduled_posts_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_scheduled_posts_user_id_scheduled_at", "user_id", "scheduled_at"),
        Index(
            "ix_scheduled_posts_dispatch",
            "status",
            "scheduled_at",
            "next_attempt_at",
            "dispatch_lease_until",
        ),
        Index(
            "ix_scheduled_posts_processing_lease",
            "status",
            "processing_lease_until",
        ),
        Index(
            "uq_scheduled_posts_linkedin_post_urn",
            "linkedin_post_urn",
            unique=True,
            postgresql_where=text("linkedin_post_urn IS NOT NULL"),
            sqlite_where=text("linkedin_post_urn IS NOT NULL"),
        ),
        Index(
            "ix_scheduled_posts_publish_approval",
            "status",
            "publish_approved_at",
            "approval_revoked_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    linkedin_connection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("linkedin_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PostStatus.SCHEDULED.value
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    linkedin_post_urn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Phase 4A publishing control fields.
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dispatch_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Durable per-post publishing approval (NULL = unapproved; never auto-set by migration).
    publish_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    publish_approved_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approval_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(  # noqa: F821
        back_populates="scheduled_posts",
        foreign_keys=[user_id],
    )
    linkedin_connection: Mapped[LinkedInConnection] = relationship(  # noqa: F821
        lazy="selectin",
    )
    publish_attempts: Mapped[list[PublishAttempt]] = relationship(  # noqa: F821
        back_populates="post",
        lazy="selectin",
        order_by="PublishAttempt.attempt_number",
    )
