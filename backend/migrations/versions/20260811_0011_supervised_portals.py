"""Add supervised portal runs and append-only step evidence.

Revision ID: 20260811_0011
Revises: 20260811_0010
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0011"
down_revision: str | None = "20260811_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supervised_portal_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("portal", sa.String(length=40), nullable=False),
        sa.Column("workflow_id", sa.String(length=100), nullable=False),
        sa.Column("browser_session_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("current_url", sa.Text(), nullable=False),
        sa.Column("allowed_origins_json", sa.JSON(), nullable=False),
        sa.Column("page_fingerprint", sa.String(length=200), nullable=False),
        sa.Column("current_match_json", sa.JSON(), nullable=True),
        sa.Column("disposition", sa.String(length=50), nullable=False),
        sa.Column("intervention_reasons_json", sa.JSON(), nullable=False),
        sa.Column("trace_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["browser_session_id"], ["browser_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("browser_session_id", name="uq_supervised_portal_browser_session"),
    )
    op.create_index("ix_supervised_portal_runs_portal", "supervised_portal_runs", ["portal"])
    op.create_index(
        "ix_supervised_portal_runs_workflow_id",
        "supervised_portal_runs",
        ["workflow_id"],
    )
    op.create_index(
        "ix_supervised_portal_runs_browser_session_id",
        "supervised_portal_runs",
        ["browser_session_id"],
    )
    op.create_index("ix_supervised_portal_runs_state", "supervised_portal_runs", ["state"])
    op.create_index(
        "ix_supervised_portal_runs_workflow_updated",
        "supervised_portal_runs",
        ["workflow_id", "updated_at"],
    )

    op.create_table(
        "supervised_portal_step_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(length=50), nullable=False),
        sa.Column("capability", sa.String(length=40), nullable=True),
        sa.Column("page_type", sa.String(length=100), nullable=False),
        sa.Column("before_fingerprint", sa.String(length=200), nullable=False),
        sa.Column("after_fingerprint", sa.String(length=200), nullable=False),
        sa.Column("action_kind", sa.String(length=40), nullable=True),
        sa.Column("action_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("intervention_reasons_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["supervised_portal_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_supervised_portal_step_sequence"),
    )
    op.create_index(
        "ix_supervised_portal_step_evidence_run_id",
        "supervised_portal_step_evidence",
        ["run_id"],
    )
    op.create_index(
        "ix_supervised_portal_step_run_created",
        "supervised_portal_step_evidence",
        ["run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supervised_portal_step_run_created",
        table_name="supervised_portal_step_evidence",
    )
    op.drop_index(
        "ix_supervised_portal_step_evidence_run_id",
        table_name="supervised_portal_step_evidence",
    )
    op.drop_table("supervised_portal_step_evidence")
    op.drop_index(
        "ix_supervised_portal_runs_workflow_updated",
        table_name="supervised_portal_runs",
    )
    op.drop_index("ix_supervised_portal_runs_state", table_name="supervised_portal_runs")
    op.drop_index(
        "ix_supervised_portal_runs_browser_session_id",
        table_name="supervised_portal_runs",
    )
    op.drop_index(
        "ix_supervised_portal_runs_workflow_id",
        table_name="supervised_portal_runs",
    )
    op.drop_index("ix_supervised_portal_runs_portal", table_name="supervised_portal_runs")
    op.drop_table("supervised_portal_runs")
