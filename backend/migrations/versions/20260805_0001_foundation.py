"""Create the append-only workflow event log.

Revision ID: 20260805_0001
Revises:
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("prior_state", sa.String(length=40), nullable=False),
        sa.Column("next_state", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("cause", sa.Text(), nullable=False),
        sa.Column("verification", sa.String(length=20), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "sequence", name="uq_workflow_event_sequence"),
    )
    op.create_index(
        "ix_workflow_events_workflow_id", "workflow_events", ["workflow_id"], unique=False
    )
    op.create_index(
        "ix_workflow_events_workflow_occurred",
        "workflow_events",
        ["workflow_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_events_workflow_occurred", table_name="workflow_events")
    op.drop_index("ix_workflow_events_workflow_id", table_name="workflow_events")
    op.drop_table("workflow_events")
