"""Application user identified by LinkedIn OIDC subject."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    # LinkedIn OIDC `sub`. This is the external identity key — never email.
    linkedin_subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    linkedin_connection: Mapped[LinkedInConnection | None] = relationship(  # noqa: F821
        back_populates="user",
        uselist=False,
        lazy="selectin",
    )
    sessions: Mapped[list[AuthSession]] = relationship(  # noqa: F821
        back_populates="user",
        lazy="selectin",
    )
    scheduled_posts: Mapped[list[ScheduledPost]] = relationship(  # noqa: F821
        back_populates="user",
        lazy="selectin",
    )
