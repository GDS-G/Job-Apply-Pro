"""Add durable browser sessions and verified browser actions.

Revision ID: 20260805_0003
Revises: 20260805_0002
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0003"
down_revision: str | None = "20260805_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "browser_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=100), nullable=False),
        sa.Column("engine", sa.String(length=20), nullable=False),
        sa.Column("profile_name", sa.String(length=80), nullable=False),
        sa.Column("user_data_dir", sa.Text(), nullable=False),
        sa.Column("artifact_dir", sa.Text(), nullable=False),
        sa.Column("headless", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("current_url", sa.Text(), nullable=False),
        sa.Column("allowed_origins_json", sa.JSON(), nullable=False),
        sa.Column("last_observation_json", sa.JSON(), nullable=True),
        sa.Column("trace_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_browser_sessions_workflow_id", "browser_sessions", ["workflow_id"])
    op.create_index("ix_browser_sessions_state", "browser_sessions", ["state"])
    op.create_index(
        "ix_browser_sessions_workflow_updated",
        "browser_sessions",
        ["workflow_id", "updated_at"],
    )

    op.create_table(
        "browser_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action_json", sa.JSON(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("observation_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["browser_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_browser_action_sequence"),
    )
    op.create_index("ix_browser_actions_session_id", "browser_actions", ["session_id"])
    op.create_index(
        "ix_browser_actions_session_created",
        "browser_actions",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_browser_actions_session_created", table_name="browser_actions")
    op.drop_index("ix_browser_actions_session_id", table_name="browser_actions")
    op.drop_table("browser_actions")
    op.drop_index("ix_browser_sessions_workflow_updated", table_name="browser_sessions")
    op.drop_index("ix_browser_sessions_state", table_name="browser_sessions")
    op.drop_index("ix_browser_sessions_workflow_id", table_name="browser_sessions")
    op.drop_table("browser_sessions")
