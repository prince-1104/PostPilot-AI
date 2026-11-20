"""Durable record of a single background publish attempt."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AttemptExecutionState


class PublishAttempt(Base):
    __tablename__ = "publish_attempts"
    __table_args__ = (
        UniqueConstraint(
            "post_id",
            "attempt_number",
            name="uq_publish_attempts_post_id_attempt_number",
        ),
        Index("ix_publish_attempts_post_id_started_at", "post_id", "started_at"),
        Index("ix_publish_attempts_execution_state", "execution_state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    post_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("scheduled_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Same value stored on scheduled_posts.current_attempt_id while processing.
    fencing_token: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, unique=True)
    execution_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AttemptExecutionState.CLAIMED.value,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sanitized_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_post_urn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    post: Mapped[ScheduledPost] = relationship(back_populates="publish_attempts")  # noqa: F821
