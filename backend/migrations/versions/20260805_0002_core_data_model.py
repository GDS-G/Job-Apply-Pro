"""Create the Core candidate, job, application, and recovery data model.

Revision ID: 20260805_0002
Revises: 20260805_0001
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0002"
down_revision: str | None = "20260805_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[str]:
    return sa.Column("id", sa.String(length=36), nullable=False)


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        _id(),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("encrypted_contact", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_profiles_status", "candidate_profiles", ["status"])

    op.create_table(
        "evidence_sources",
        _id(),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=60), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_sources_profile_id", "evidence_sources", ["profile_id"])

    op.create_table(
        "candidate_claims",
        _id(),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_source_id", sa.String(length=36), nullable=True),
        sa.Column("claim_type", sa.String(length=80), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["evidence_source_id"], ["evidence_sources.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_claims_profile_id", "candidate_claims", ["profile_id"])

    op.create_table(
        "documents",
        _id(),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_profile_id", "documents", ["profile_id"])

    op.create_table(
        "document_versions",
        _id(),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version", name="uq_document_version"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])

    op.create_table(
        "jobs",
        _id(),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("employer", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("description_hash", sa.String(length=64), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_job_source_id"),
    )
    op.create_index("ix_jobs_employer", "jobs", ["employer"])

    op.create_table(
        "job_requirements",
        _id(),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_requirements_job_id", "job_requirements", ["job_id"])

    op.create_table(
        "fit_scores",
        _id(),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("explanation_json", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fit_scores_job_id", "fit_scores", ["job_id"])
    op.create_index("ix_fit_scores_profile_id", "fit_scores", ["profile_id"])

    op.create_table(
        "applications",
        _id(),
        sa.Column("workflow_id", sa.String(length=100), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("selected_document_version_id", sa.String(length=36), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
        sa.ForeignKeyConstraint(["selected_document_version_id"], ["document_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id"),
    )
    op.create_index("ix_applications_job_id", "applications", ["job_id"])
    op.create_index("ix_applications_profile_id", "applications", ["profile_id"])
    op.create_index("ix_applications_workflow_id", "applications", ["workflow_id"])

    op.create_table(
        "application_answers",
        _id(),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("canonical_field", sa.String(length=60), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("provenance", sa.String(length=200), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_answers_application_id", "application_answers", ["application_id"]
    )

    op.create_table(
        "workflow_checkpoints",
        _id(),
        sa.Column("workflow_id", sa.String(length=100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("page_fingerprint", sa.String(length=200), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "sequence", name="uq_workflow_checkpoint_sequence"),
    )
    op.create_index(
        "ix_workflow_checkpoints_latest",
        "workflow_checkpoints",
        ["workflow_id", "sequence"],
    )

    op.create_table(
        "model_invocations",
        _id(),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_micros", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "error_records",
        _id(),
        sa.Column("workflow_id", sa.String(length=100), nullable=True),
        sa.Column("classification", sa.String(length=40), nullable=False),
        sa.Column("component", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=200), nullable=False),
        sa.Column("sanitized_context_json", sa.JSON(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_error_records_workflow_id", "error_records", ["workflow_id"])


def downgrade() -> None:
    for table, indexes in (
        ("error_records", ["ix_error_records_workflow_id"]),
        ("model_invocations", []),
        ("workflow_checkpoints", ["ix_workflow_checkpoints_latest"]),
        ("application_answers", ["ix_application_answers_application_id"]),
        (
            "applications",
            ["ix_applications_workflow_id", "ix_applications_profile_id", "ix_applications_job_id"],
        ),
        ("fit_scores", ["ix_fit_scores_profile_id", "ix_fit_scores_job_id"]),
        ("job_requirements", ["ix_job_requirements_job_id"]),
        ("jobs", ["ix_jobs_employer"]),
        ("document_versions", ["ix_document_versions_document_id"]),
        ("documents", ["ix_documents_profile_id"]),
        ("candidate_claims", ["ix_candidate_claims_profile_id"]),
        ("evidence_sources", ["ix_evidence_sources_profile_id"]),
        ("candidate_profiles", ["ix_candidate_profiles_status"]),
    ):
        for index in indexes:
            op.drop_index(index, table_name=table)
        op.drop_table(table)
