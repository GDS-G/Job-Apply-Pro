"""Add complete application-answer provenance and review state.

Revision ID: 20260812_0019
Revises: 20260812_0018
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0019"
down_revision: str | None = "20260812_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("application_answers") as batch:
        batch.alter_column("canonical_field", type_=sa.String(length=160))
        batch.add_column(sa.Column("profile_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("job_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("encrypted_question", sa.Text(), nullable=True))
        batch.add_column(sa.Column("encrypted_normalized_question", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "status",
                sa.String(length=40),
                nullable=False,
                server_default="LEGACY_REVIEW_REQUIRED",
            )
        )
        batch.add_column(
            sa.Column("source_type", sa.String(length=40), nullable=False, server_default="LEGACY")
        )
        batch.add_column(sa.Column("source_answer_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("library_answer_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column("evidence_claim_ids_json", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("retrieval_results_json", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(sa.Column("provider_id", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("model_id", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("prompt_version", sa.String(length=40), nullable=True))
        batch.add_column(
            sa.Column(
                "policy_version",
                sa.String(length=40),
                nullable=False,
                server_default="answer-drafting/1.0",
            )
        )
        batch.add_column(sa.Column("encrypted_generated_value", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("character_limit", sa.Integer(), nullable=False, server_default="20000")
        )
        batch.add_column(
            sa.Column(
                "character_limit_applied", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(
            sa.Column("limitations_json", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("user_edited", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column(
                "reuse_permission",
                sa.String(length=30),
                nullable=False,
                server_default="APPLICATIONS",
            )
        )
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_application_answers_profile", "candidate_profiles", ["profile_id"], ["id"]
        )
        batch.create_foreign_key("fk_application_answers_job", "jobs", ["job_id"], ["id"])
        batch.create_foreign_key(
            "fk_application_answers_library", "answer_library", ["library_answer_id"], ["id"]
        )
        batch.create_index("ix_application_answers_profile_id", ["profile_id"])
        batch.create_index("ix_application_answers_job_id", ["job_id"])
        batch.create_index("ix_application_answers_status", ["status"])

    op.execute(
        sa.text(
            """
            UPDATE application_answers
            SET profile_id = (
                    SELECT profile_id FROM applications
                    WHERE applications.id = application_answers.application_id
                ),
                job_id = (
                    SELECT job_id FROM applications
                    WHERE applications.id = application_answers.application_id
                ),
                updated_at = created_at
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("application_answers") as batch:
        batch.drop_index("ix_application_answers_status")
        batch.drop_index("ix_application_answers_job_id")
        batch.drop_index("ix_application_answers_profile_id")
        batch.drop_constraint("fk_application_answers_library", type_="foreignkey")
        batch.drop_constraint("fk_application_answers_job", type_="foreignkey")
        batch.drop_constraint("fk_application_answers_profile", type_="foreignkey")
        for column in (
            "updated_at",
            "reuse_permission",
            "user_edited",
            "limitations_json",
            "character_limit_applied",
            "character_limit",
            "encrypted_generated_value",
            "policy_version",
            "prompt_version",
            "model_id",
            "provider_id",
            "retrieval_results_json",
            "evidence_claim_ids_json",
            "library_answer_id",
            "source_answer_id",
            "source_type",
            "status",
            "encrypted_normalized_question",
            "encrypted_question",
            "revision",
            "job_id",
            "profile_id",
        ):
            batch.drop_column(column)
        batch.alter_column("canonical_field", type_=sa.String(length=60))
