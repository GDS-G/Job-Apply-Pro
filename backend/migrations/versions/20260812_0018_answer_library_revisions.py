"""Add governed answer-library revisions.

Revision ID: 20260812_0018
Revises: 20260812_0017
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0018"
down_revision: str | None = "20260812_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("answer_library") as batch:
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))

    op.create_table(
        "answer_library_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "answer_id", sa.String(length=36), sa.ForeignKey("answer_library.id"), nullable=False
        ),
        sa.Column(
            "profile_id",
            sa.String(length=36),
            sa.ForeignKey("candidate_profiles.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("encrypted_question", sa.Text(), nullable=False),
        sa.Column("canonical_field", sa.String(length=160), nullable=False),
        sa.Column("encrypted_answer", sa.Text(), nullable=False),
        sa.Column("evidence_claim_ids_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("reuse_permission", sa.String(length=30), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("answer_id", "revision", name="uq_answer_library_revision"),
    )
    op.create_index(
        "ix_answer_library_revisions_answer_id", "answer_library_revisions", ["answer_id"]
    )
    op.create_index(
        "ix_answer_library_revisions_profile_id", "answer_library_revisions", ["profile_id"]
    )
    op.create_index(
        "ix_answer_library_revisions_answer_created",
        "answer_library_revisions",
        ["answer_id", "created_at"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO answer_library_revisions (
                id, answer_id, profile_id, revision, encrypted_question,
                canonical_field, encrypted_answer, evidence_claim_ids_json,
                confidence, approved, locked, reuse_permission, provenance_json, created_at
            )
            SELECT
                id, id, profile_id, 1, encrypted_question,
                canonical_field, encrypted_answer, evidence_claim_ids_json,
                confidence, approved, locked, reuse_permission, provenance_json, updated_at
            FROM answer_library
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_answer_library_revisions_answer_created", table_name="answer_library_revisions"
    )
    op.drop_index("ix_answer_library_revisions_profile_id", table_name="answer_library_revisions")
    op.drop_index("ix_answer_library_revisions_answer_id", table_name="answer_library_revisions")
    op.drop_table("answer_library_revisions")
    with op.batch_alter_table("answer_library") as batch:
        batch.drop_column("revision")
