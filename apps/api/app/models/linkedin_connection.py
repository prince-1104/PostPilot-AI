"""Stored LinkedIn authorization for a user. Access tokens are encrypted at rest."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ConnectionStatus


class LinkedInConnection(Base):
    __tablename__ = "linkedin_connections"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    # OIDC subject for the LinkedIn identity this connection belongs to.
    provider_subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Versioned AES-GCM blob. Never store plaintext tokens.
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    granted_scopes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    connection_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ConnectionStatus.CONNECTED.value
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

    user: Mapped[User] = relationship(back_populates="linkedin_connection")  # noqa: F821
