"""Add evidence-bound document generation audits.

Revision ID: 20260811_0012
Revises: 20260811_0011
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0012"
down_revision: str | None = "20260811_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_generation_audits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("document_version_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("output_format", sa.String(length=20), nullable=False),
        sa.Column("review_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("evidence_claim_ids_json", sa.JSON(), nullable=False),
        sa.Column("requirement_ids_json", sa.JSON(), nullable=False),
        sa.Column("missing_required_requirements_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_version_id"),
    )
    op.create_index(
        "ix_document_generation_audits_application_id",
        "document_generation_audits",
        ["application_id"],
    )
    op.create_index(
        "ix_document_generation_audits_profile_id",
        "document_generation_audits",
        ["profile_id"],
    )
    op.create_index(
        "ix_document_generation_audits_job_id",
        "document_generation_audits",
        ["job_id"],
    )
    op.create_index(
        "ix_document_generation_audits_document_version_id",
        "document_generation_audits",
        ["document_version_id"],
        unique=True,
    )
    op.create_table(
        "submitted_document_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("document_version_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("upload_fingerprint", sa.String(length=200), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id",
            "document_version_id",
            "role",
            "upload_fingerprint",
            name="uq_submitted_document_capture",
        ),
    )
    op.create_index(
        "ix_submitted_document_evidence_application_id",
        "submitted_document_evidence",
        ["application_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_submitted_document_evidence_application_id",
        table_name="submitted_document_evidence",
    )
    op.drop_table("submitted_document_evidence")
    op.drop_index(
        "ix_document_generation_audits_document_version_id",
        table_name="document_generation_audits",
    )
    op.drop_index("ix_document_generation_audits_job_id", table_name="document_generation_audits")
    op.drop_index(
        "ix_document_generation_audits_profile_id",
        table_name="document_generation_audits",
    )
    op.drop_index(
        "ix_document_generation_audits_application_id",
        table_name="document_generation_audits",
    )
    op.drop_table("document_generation_audits")
