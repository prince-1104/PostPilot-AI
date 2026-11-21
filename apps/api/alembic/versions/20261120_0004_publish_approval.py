"""Add durable per-post publishing approval fields.

Revision ID: 20261120_0004
Revises: 20261120_0003
Create Date: 2026-11-21

Existing rows remain unapproved (nullable approval timestamps stay NULL).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261120_0004"
down_revision: str | None = "20261120_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scheduled_posts",
        sa.Column("publish_approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_posts",
        sa.Column("publish_approved_by", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "scheduled_posts",
        sa.Column("approved_content_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "scheduled_posts",
        sa.Column("approved_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "scheduled_posts",
        sa.Column("approval_revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_scheduled_posts_publish_approved_by_users",
        "scheduled_posts",
        "users",
        ["publish_approved_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_scheduled_posts_publish_approval",
        "scheduled_posts",
        ["status", "publish_approved_at", "approval_revoked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_posts_publish_approval", table_name="scheduled_posts")
    op.drop_constraint(
        "fk_scheduled_posts_publish_approved_by_users",
        "scheduled_posts",
        type_="foreignkey",
    )
    op.drop_column("scheduled_posts", "approval_revoked_at")
    op.drop_column("scheduled_posts", "approved_version")
    op.drop_column("scheduled_posts", "approved_content_hash")
    op.drop_column("scheduled_posts", "publish_approved_by")
    op.drop_column("scheduled_posts", "publish_approved_at")
