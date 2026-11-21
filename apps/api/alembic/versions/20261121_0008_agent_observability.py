"""Phase 5D: LLM usage events, node traces, model pricing versions.

Revision ID: 20261121_0008
Revises: 20261121_0007
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261121_0008"
down_revision: str | None = "20261121_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_pricing_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pricing_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("input_per_million", sa.Numeric(18, 8), nullable=False),
        sa.Column("cached_input_per_million", sa.Numeric(18, 8), nullable=True),
        sa.Column("output_per_million", sa.Numeric(18, 8), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pricing_version", "model", name="uq_model_pricing_versions_version_model"
        ),
    )
    op.create_index("ix_model_pricing_versions_model", "model_pricing_versions", ["model"])

    op.create_table(
        "llm_usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=True),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("schema_name", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("usage_known", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(18, 8), nullable=True),
        sa.Column("cost_currency", sa.String(length=8), nullable=True),
        sa.Column("pricing_version", sa.String(length=64), nullable=True),
        sa.Column("cost_available", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_threads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_llm_usage_events_idempotency"),
    )
    op.create_index(
        "ix_llm_usage_events_user_created", "llm_usage_events", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_llm_usage_events_thread_created", "llm_usage_events", ["thread_id", "created_at"]
    )
    op.create_index("ix_llm_usage_events_trace", "llm_usage_events", ["trace_id"])
    op.create_index(
        "ix_llm_usage_events_model_created", "llm_usage_events", ["model", "created_at"]
    )

    op.create_table(
        "agent_node_traces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=True),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("usage_event_id", sa.Uuid(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("review_passed", sa.Boolean(), nullable=True),
        sa.Column("revision_count", sa.Integer(), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_threads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["usage_event_id"], ["llm_usage_events.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_agent_node_traces_idempotency"),
    )
    op.create_index(
        "ix_agent_node_traces_user_started", "agent_node_traces", ["user_id", "started_at"]
    )
    op.create_index(
        "ix_agent_node_traces_thread_started",
        "agent_node_traces",
        ["thread_id", "started_at"],
    )
    op.create_index("ix_agent_node_traces_trace", "agent_node_traces", ["trace_id"])
    op.create_index(
        "ix_agent_node_traces_node", "agent_node_traces", ["node_name", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_node_traces_node", table_name="agent_node_traces")
    op.drop_index("ix_agent_node_traces_trace", table_name="agent_node_traces")
    op.drop_index("ix_agent_node_traces_thread_started", table_name="agent_node_traces")
    op.drop_index("ix_agent_node_traces_user_started", table_name="agent_node_traces")
    op.drop_table("agent_node_traces")
    op.drop_index("ix_llm_usage_events_model_created", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_trace", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_thread_created", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_user_created", table_name="llm_usage_events")
    op.drop_table("llm_usage_events")
    op.drop_index("ix_model_pricing_versions_model", table_name="model_pricing_versions")
    op.drop_table("model_pricing_versions")
