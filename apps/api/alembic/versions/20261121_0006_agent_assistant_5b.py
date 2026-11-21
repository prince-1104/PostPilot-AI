"""Phase 5B assistant concurrency + message idempotency.

Revision ID: 20261121_0006
Revises: 20261121_0005
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261121_0006"
down_revision: str | None = "20261121_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_threads",
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_messages",
        sa.Column("client_message_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "uq_agent_messages_thread_client_message_id",
        "agent_messages",
        ["thread_id", "client_message_id"],
        unique=True,
        postgresql_where=sa.text("client_message_id IS NOT NULL"),
        sqlite_where=sa.text("client_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_agent_messages_thread_client_message_id",
        table_name="agent_messages",
    )
    op.drop_column("agent_messages", "client_message_id")
    op.drop_column("agent_threads", "lock_version")
