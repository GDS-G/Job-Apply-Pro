"""Add CAPTCHA, questionnaire, assessment, and quiz session persistence.

Revision ID: 20260805_0007
Revises: 20260805_0006
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0007"
down_revision: str | None = "20260805_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "challenge_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=100), nullable=False),
        sa.Column("browser_session_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["browser_session_id"], ["browser_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_challenge_sessions_workflow_id", "challenge_sessions", ["workflow_id"])
    op.create_index(
        "ix_challenge_sessions_browser_session_id",
        "challenge_sessions",
        ["browser_session_id"],
    )
    op.create_index("ix_challenge_sessions_kind", "challenge_sessions", ["kind"])
    op.create_index("ix_challenge_sessions_status", "challenge_sessions", ["status"])
    op.create_index(
        "ix_challenge_sessions_workflow_updated",
        "challenge_sessions",
        ["workflow_id", "updated_at"],
    )
    op.create_table(
        "challenge_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["challenge_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_challenge_event_sequence"),
    )
    op.create_index("ix_challenge_events_session_id", "challenge_events", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_challenge_events_session_id", table_name="challenge_events")
    op.drop_table("challenge_events")
    op.drop_index("ix_challenge_sessions_workflow_updated", table_name="challenge_sessions")
    op.drop_index("ix_challenge_sessions_status", table_name="challenge_sessions")
    op.drop_index("ix_challenge_sessions_kind", table_name="challenge_sessions")
    op.drop_index("ix_challenge_sessions_browser_session_id", table_name="challenge_sessions")
    op.drop_index("ix_challenge_sessions_workflow_id", table_name="challenge_sessions")
    op.drop_table("challenge_sessions")
