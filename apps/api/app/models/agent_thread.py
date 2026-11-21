"""AI assistant conversation threads (Phase 5A)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.enums import AgentThreadStatus

# JSONB on Postgres; portable JSON elsewhere (SQLite unit tests).
_JsonPayload = JSON().with_variant(JSONB(), "postgresql")


class AgentThread(Base):
    __tablename__ = "agent_threads"
    __table_args__ = (Index("ix_agent_threads_user_id_updated_at", "user_id", "updated_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=AgentThreadStatus.ACTIVE.value
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optimistic concurrency token for draft edits / concurrent turns.
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Single source of truth for LangGraph working state (no separate checkpoint table).
    graph_state: Mapped[dict[str, Any]] = mapped_column(
        _JsonPayload, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="agent_threads")  # noqa: F821
    messages: Mapped[list[AgentMessage]] = relationship(
        back_populates="thread",
        lazy="selectin",
        order_by="AgentMessage.created_at",
        cascade="all, delete-orphan",
    )
    drafts: Mapped[list[AgentDraft]] = relationship(
        back_populates="thread",
        lazy="selectin",
        order_by="AgentDraft.version",
        cascade="all, delete-orphan",
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        Index("ix_agent_messages_thread_id_created_at", "thread_id", "created_at"),
        Index(
            "uq_agent_messages_thread_client_message_id",
            "thread_id",
            "client_message_id",
            unique=True,
            postgresql_where=text("client_message_id IS NOT NULL"),
            sqlite_where=text("client_message_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Client-supplied idempotency key for user turns (unique per thread when set).
    client_message_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    thread: Mapped[AgentThread] = relationship(back_populates="messages")


class AgentDraft(Base):
    __tablename__ = "agent_drafts"
    __table_args__ = (Index("ix_agent_drafts_thread_id_version", "thread_id", "version"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_facts: Mapped[dict[str, Any]] = mapped_column(
        _JsonPayload, nullable=False, default=dict
    )
    suggested_details: Mapped[dict[str, Any]] = mapped_column(
        _JsonPayload, nullable=False, default=dict
    )
    assumptions: Mapped[dict[str, Any]] = mapped_column(
        _JsonPayload, nullable=False, default=dict
    )
    proposed_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Set when this draft version was confirmed into PostService (Phase 5C).
    scheduled_post_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("scheduled_posts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    thread: Mapped[AgentThread] = relationship(back_populates="drafts")
    schedule_ops: Mapped[list[AgentDraftScheduleOp]] = relationship(
        back_populates="draft",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class AgentDraftScheduleOp(Base):
    """Idempotent confirmation that links an AI draft version to a ScheduledPost."""

    __tablename__ = "agent_draft_schedule_ops"
    __table_args__ = (
        Index(
            "uq_agent_draft_schedule_ops_user_idempotency",
            "user_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "uq_agent_draft_schedule_ops_draft_version_confirmed",
            "draft_id",
            "draft_version",
            unique=True,
            postgresql_where=text("state = 'confirmed'"),
            sqlite_where=text("state = 'confirmed'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    draft_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    linkedin_connection_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_post_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("scheduled_posts.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    warnings_acknowledged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    advisory_warnings: Mapped[list[Any]] = mapped_column(
        _JsonPayload, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    draft: Mapped[AgentDraft] = relationship(back_populates="schedule_ops")
