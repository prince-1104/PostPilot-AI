"""Add publishing leases, attempt tracking, and requires_review support.

Revision ID: 20261120_0003
Revises: 20261120_0002
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261120_0003"
down_revision: str | None = "20261120_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scheduled_posts",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_posts",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "scheduled_posts",
        sa.Column("dispatch_lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_posts",
        sa.Column("processing_lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_posts",
        sa.Column("current_attempt_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "scheduled_posts",
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "scheduled_posts",
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_scheduled_posts_dispatch",
        "scheduled_posts",
        ["status", "scheduled_at", "next_attempt_at", "dispatch_lease_until"],
    )
    op.create_index(
        "ix_scheduled_posts_processing_lease",
        "scheduled_posts",
        ["status", "processing_lease_until"],
    )

    op.create_table(
        "publish_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.Uuid(), nullable=False),
        sa.Column("execution_state", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_http_status", sa.Integer(), nullable=True),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("sanitized_error_code", sa.String(length=128), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_post_urn", sa.String(length=255), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["scheduled_posts.id"],
            name=op.f("fk_publish_attempts_post_id_scheduled_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_attempts")),
        sa.UniqueConstraint(
            "post_id",
            "attempt_number",
            name="uq_publish_attempts_post_id_attempt_number",
        ),
        sa.UniqueConstraint("fencing_token", name="uq_publish_attempts_fencing_token"),
    )
    op.create_index(op.f("ix_publish_attempts_post_id"), "publish_attempts", ["post_id"])
    op.create_index(
        "ix_publish_attempts_post_id_started_at",
        "publish_attempts",
        ["post_id", "started_at"],
    )
    op.create_index(
        "ix_publish_attempts_execution_state",
        "publish_attempts",
        ["execution_state"],
    )


def downgrade() -> None:
    op.drop_index("ix_publish_attempts_execution_state", table_name="publish_attempts")
    op.drop_index("ix_publish_attempts_post_id_started_at", table_name="publish_attempts")
    op.drop_index(op.f("ix_publish_attempts_post_id"), table_name="publish_attempts")
    op.drop_table("publish_attempts")
    op.drop_index("ix_scheduled_posts_processing_lease", table_name="scheduled_posts")
    op.drop_index("ix_scheduled_posts_dispatch", table_name="scheduled_posts")
    op.drop_column("scheduled_posts", "last_error_at")
    op.drop_column("scheduled_posts", "last_error_code")
    op.drop_column("scheduled_posts", "current_attempt_id")
    op.drop_column("scheduled_posts", "processing_lease_until")
    op.drop_column("scheduled_posts", "dispatch_lease_until")
    op.drop_column("scheduled_posts", "attempt_count")
    op.drop_column("scheduled_posts", "next_attempt_at")
