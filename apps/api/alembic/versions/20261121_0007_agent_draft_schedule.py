"""Phase 5C: link AI drafts to scheduled posts via confirmation ops.

Revision ID: 20261121_0007
Revises: 20261121_0006
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261121_0007"
down_revision: str | None = "20261121_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_drafts",
        sa.Column("scheduled_post_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_agent_drafts_scheduled_post_id",
        "agent_drafts",
        ["scheduled_post_id"],
    )
    op.create_foreign_key(
        "fk_agent_drafts_scheduled_post_id",
        "agent_drafts",
        "scheduled_posts",
        ["scheduled_post_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "agent_draft_schedule_ops",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("content_snapshot", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("linkedin_connection_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("scheduled_post_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("warnings_acknowledged", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "advisory_warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["draft_id"], ["agent_drafts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["scheduled_post_id"], ["scheduled_posts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_draft_schedule_ops_draft_id",
        "agent_draft_schedule_ops",
        ["draft_id"],
    )
    op.create_index(
        "ix_agent_draft_schedule_ops_user_id",
        "agent_draft_schedule_ops",
        ["user_id"],
    )
    op.create_index(
        "uq_agent_draft_schedule_ops_user_idempotency",
        "agent_draft_schedule_ops",
        ["user_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "uq_agent_draft_schedule_ops_draft_version_confirmed",
        "agent_draft_schedule_ops",
        ["draft_id", "draft_version"],
        unique=True,
        postgresql_where=sa.text("state = 'confirmed'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_agent_draft_schedule_ops_draft_version_confirmed",
        table_name="agent_draft_schedule_ops",
    )
    op.drop_index(
        "uq_agent_draft_schedule_ops_user_idempotency",
        table_name="agent_draft_schedule_ops",
    )
    op.drop_index("ix_agent_draft_schedule_ops_user_id", table_name="agent_draft_schedule_ops")
    op.drop_index("ix_agent_draft_schedule_ops_draft_id", table_name="agent_draft_schedule_ops")
    op.drop_table("agent_draft_schedule_ops")
    op.drop_constraint("fk_agent_drafts_scheduled_post_id", "agent_drafts", type_="foreignkey")
    op.drop_index("ix_agent_drafts_scheduled_post_id", table_name="agent_drafts")
    op.drop_column("agent_drafts", "scheduled_post_id")
