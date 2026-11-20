"""Create scheduled_posts for Phase 3 scheduling.

Revision ID: 20261120_0002
Revises: 20261120_0001
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261120_0002"
down_revision: str | None = "20261120_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("linkedin_connection_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("linkedin_post_urn", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["linkedin_connection_id"],
            ["linkedin_connections.id"],
            name=op.f("fk_scheduled_posts_linkedin_connection_id_linkedin_connections"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_scheduled_posts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_posts")),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_scheduled_posts_user_id_idempotency_key",
        ),
    )
    op.create_index(op.f("ix_scheduled_posts_user_id"), "scheduled_posts", ["user_id"])
    op.create_index(
        "ix_scheduled_posts_status_scheduled_at",
        "scheduled_posts",
        ["status", "scheduled_at"],
    )
    op.create_index(
        "ix_scheduled_posts_user_id_scheduled_at",
        "scheduled_posts",
        ["user_id", "scheduled_at"],
    )
    op.create_index(
        "uq_scheduled_posts_linkedin_post_urn",
        "scheduled_posts",
        ["linkedin_post_urn"],
        unique=True,
        postgresql_where=sa.text("linkedin_post_urn IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_scheduled_posts_linkedin_post_urn",
        table_name="scheduled_posts",
        postgresql_where=sa.text("linkedin_post_urn IS NOT NULL"),
    )
    op.drop_index("ix_scheduled_posts_user_id_scheduled_at", table_name="scheduled_posts")
    op.drop_index("ix_scheduled_posts_status_scheduled_at", table_name="scheduled_posts")
    op.drop_index(op.f("ix_scheduled_posts_user_id"), table_name="scheduled_posts")
    op.drop_table("scheduled_posts")
