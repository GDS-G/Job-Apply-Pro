"""Add Candidate Knowledge document, claim, answer, and retrieval persistence.

Revision ID: 20260805_0004
Revises: 20260805_0003
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0004"
down_revision: str | None = "20260805_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(
            sa.Column(
                "variant_label", sa.String(length=120), nullable=False, server_default="General"
            )
        )
        batch.add_column(
            sa.Column("job_family_tags_json", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    with op.batch_alter_table("document_versions") as batch:
        batch.add_column(
            sa.Column("encrypted_extraction", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column(
                "parser_version", sa.String(length=100), nullable=False, server_default="legacy"
            )
        )
        batch.add_column(sa.Column("page_count", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(
            sa.Column("character_count", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("evidence_sources") as batch:
        batch.add_column(sa.Column("document_version_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column(
                "source_label",
                sa.String(length=255),
                nullable=False,
                server_default="Imported source",
            )
        )
        batch.create_foreign_key(
            "fk_evidence_sources_document_version",
            "document_versions",
            ["document_version_id"],
            ["id"],
        )
        batch.create_index("ix_evidence_sources_document_version_id", ["document_version_id"])

    with op.batch_alter_table("candidate_claims") as batch:
        batch.add_column(
            sa.Column(
                "canonical_key", sa.String(length=160), nullable=False, server_default="legacy"
            )
        )
        batch.add_column(
            sa.Column("statement", sa.Text(), nullable=False, server_default="Legacy claim")
        )
        batch.add_column(sa.Column("source_location", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("context_json", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("start_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("end_date", sa.Date(), nullable=True))
        batch.add_column(
            sa.Column(
                "verification_status",
                sa.String(length=20),
                nullable=False,
                server_default="PROPOSED",
            )
        )
        batch.add_column(
            sa.Column(
                "permitted_use",
                sa.String(length=30),
                nullable=False,
                server_default="PROFILE_ONLY",
            )
        )
        batch.add_column(
            sa.Column(
                "sensitivity", sa.String(length=20), nullable=False, server_default="PERSONAL"
            )
        )
        batch.add_column(sa.Column("superseded_by_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            )
        )
        batch.create_foreign_key(
            "fk_candidate_claims_superseded_by",
            "candidate_claims",
            ["superseded_by_id"],
            ["id"],
        )
        batch.create_index("ix_candidate_claims_canonical_key", ["canonical_key"])
        batch.create_index("ix_candidate_claims_verification_status", ["verification_status"])

    op.create_table(
        "answer_library",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("canonical_field", sa.String(length=160), nullable=False),
        sa.Column("encrypted_question", sa.Text(), nullable=False),
        sa.Column("encrypted_answer", sa.Text(), nullable=False),
        sa.Column("evidence_claim_ids_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("reuse_permission", sa.String(length=30), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
    )
    op.create_index("ix_answer_library_profile_id", "answer_library", ["profile_id"])
    op.create_index("ix_answer_library_canonical_field", "answer_library", ["canonical_field"])
    op.create_index(
        "ix_answer_library_profile_updated", "answer_library", ["profile_id", "updated_at"]
    )

    op.create_table(
        "retrieval_chunks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("canonical_key", sa.String(length=160), nullable=False),
        sa.Column("encrypted_content", sa.Text(), nullable=False),
        sa.Column("token_hashes_json", sa.JSON(), nullable=False),
        sa.Column("vector_json", sa.JSON(), nullable=False),
        sa.Column("permitted_use", sa.String(length=30), nullable=False),
        sa.Column("evidence_claim_ids_json", sa.JSON(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
        sa.UniqueConstraint("source_type", "source_id", name="uq_retrieval_chunk_source"),
    )
    op.create_index("ix_retrieval_chunks_profile_id", "retrieval_chunks", ["profile_id"])
    op.create_index(
        "ix_retrieval_chunks_profile_source",
        "retrieval_chunks",
        ["profile_id", "source_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_chunks_profile_source", table_name="retrieval_chunks")
    op.drop_index("ix_retrieval_chunks_profile_id", table_name="retrieval_chunks")
    op.drop_table("retrieval_chunks")
    op.drop_index("ix_answer_library_profile_updated", table_name="answer_library")
    op.drop_index("ix_answer_library_canonical_field", table_name="answer_library")
    op.drop_index("ix_answer_library_profile_id", table_name="answer_library")
    op.drop_table("answer_library")

    with op.batch_alter_table("candidate_claims") as batch:
        batch.drop_index("ix_candidate_claims_verification_status")
        batch.drop_index("ix_candidate_claims_canonical_key")
        batch.drop_constraint("fk_candidate_claims_superseded_by", type_="foreignkey")
        for column in (
            "updated_at",
            "superseded_by_id",
            "sensitivity",
            "permitted_use",
            "verification_status",
            "end_date",
            "start_date",
            "context_json",
            "source_location",
            "statement",
            "canonical_key",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("evidence_sources") as batch:
        batch.drop_index("ix_evidence_sources_document_version_id")
        batch.drop_constraint("fk_evidence_sources_document_version", type_="foreignkey")
        batch.drop_column("source_label")
        batch.drop_column("document_version_id")

    with op.batch_alter_table("document_versions") as batch:
        batch.drop_column("character_count")
        batch.drop_column("page_count")
        batch.drop_column("parser_version")
        batch.drop_column("encrypted_extraction")

    with op.batch_alter_table("documents") as batch:
        batch.drop_column("archived")
        batch.drop_column("is_primary")
        batch.drop_column("job_family_tags_json")
        batch.drop_column("variant_label")
