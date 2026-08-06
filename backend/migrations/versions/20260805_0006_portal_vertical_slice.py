"""Add persisted reference ATS vertical-slice runs.

Revision ID: 20260805_0006
Revises: 20260805_0005
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0006"
down_revision: str | None = "20260805_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portal_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("portal", sa.String(length=40), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("workflow_id", sa.String(length=100), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("browser_session_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("portal_origin", sa.Text(), nullable=False),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column("deduplicated", sa.Boolean(), nullable=False),
        sa.Column("qualification_json", sa.JSON(), nullable=False),
        sa.Column("selected_document_version_id", sa.String(length=36), nullable=False),
        sa.Column("field_mappings_json", sa.JSON(), nullable=False),
        sa.Column("review_fingerprint", sa.String(length=200), nullable=False),
        sa.Column("submission_evidence_json", sa.JSON(), nullable=True),
        sa.Column("trace_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["browser_session_id"], ["browser_sessions.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
        sa.ForeignKeyConstraint(["selected_document_version_id"], ["document_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id"),
    )
    op.create_index("ix_portal_runs_workflow_id", "portal_runs", ["workflow_id"])
    op.create_index("ix_portal_runs_application_id", "portal_runs", ["application_id"])
    op.create_index("ix_portal_runs_browser_session_id", "portal_runs", ["browser_session_id"])
    op.create_index("ix_portal_runs_profile_id", "portal_runs", ["profile_id"])
    op.create_index("ix_portal_runs_job_id", "portal_runs", ["job_id"])
    op.create_index("ix_portal_runs_state", "portal_runs", ["state"])
    op.create_index(
        "ix_portal_runs_workflow_updated",
        "portal_runs",
        ["workflow_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_portal_runs_workflow_updated", table_name="portal_runs")
    op.drop_index("ix_portal_runs_state", table_name="portal_runs")
    op.drop_index("ix_portal_runs_job_id", table_name="portal_runs")
    op.drop_index("ix_portal_runs_profile_id", table_name="portal_runs")
    op.drop_index("ix_portal_runs_browser_session_id", table_name="portal_runs")
    op.drop_index("ix_portal_runs_application_id", table_name="portal_runs")
    op.drop_index("ix_portal_runs_workflow_id", table_name="portal_runs")
    op.drop_table("portal_runs")
