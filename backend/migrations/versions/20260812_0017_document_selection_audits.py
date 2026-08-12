"""Add explainable document selection audits.

Revision ID: 20260812_0017
Revises: 20260812_0016
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0017"
down_revision: str | None = "20260812_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_selection_audits",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "application_id", sa.String(length=36), sa.ForeignKey("applications.id"), nullable=False
        ),
        sa.Column(
            "profile_id",
            sa.String(length=36),
            sa.ForeignKey("candidate_profiles.id"),
            nullable=False,
        ),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column(
            "document_id", sa.String(length=36), sa.ForeignKey("documents.id"), nullable=False
        ),
        sa.Column(
            "document_version_id",
            sa.String(length=36),
            sa.ForeignKey("document_versions.id"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("review_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("criteria_json", sa.JSON(), nullable=False),
        sa.Column("reasons_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_document_selection_audits_application_id",
        "document_selection_audits",
        ["application_id"],
    )
    op.create_index(
        "ix_document_selection_audits_profile_id",
        "document_selection_audits",
        ["profile_id"],
    )
    op.create_index(
        "ix_document_selection_audits_job_id",
        "document_selection_audits",
        ["job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_selection_audits_job_id", table_name="document_selection_audits")
    op.drop_index("ix_document_selection_audits_profile_id", table_name="document_selection_audits")
    op.drop_index(
        "ix_document_selection_audits_application_id",
        table_name="document_selection_audits",
    )
    op.drop_table("document_selection_audits")
