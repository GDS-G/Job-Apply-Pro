"""Add reviewed application field bindings.

Revision ID: 20260812_0021
Revises: 20260812_0020
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0021"
down_revision: str | None = "20260812_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_field_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("application_answer_id", sa.String(length=36), nullable=False),
        sa.Column("answer_revision", sa.Integer(), nullable=False),
        sa.Column("portal", sa.String(length=80), nullable=False),
        sa.Column("page_fingerprint", sa.String(length=200), nullable=False),
        sa.Column("control_key", sa.String(length=200), nullable=False),
        sa.Column("control_kind", sa.String(length=40), nullable=False),
        sa.Column("encrypted_label", sa.Text(), nullable=False),
        sa.Column("encrypted_options", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("canonical_field", sa.String(length=160), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("binding_source", sa.String(length=40), nullable=False),
        sa.Column("answer_source", sa.String(length=40), nullable=False),
        sa.Column("answer_kind", sa.String(length=40), nullable=False),
        sa.Column("validation_rules_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("automation_permission", sa.String(length=40), nullable=False),
        sa.Column("review_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["application_answer_id"], ["application_answers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id",
            "page_fingerprint",
            "control_key",
            name="uq_application_field_binding_control",
        ),
    )
    op.create_index(
        "ix_application_field_bindings_application_id",
        "application_field_bindings",
        ["application_id"],
    )
    op.create_index(
        "ix_application_field_bindings_application_answer_id",
        "application_field_bindings",
        ["application_answer_id"],
    )
    op.create_index(
        "ix_application_field_bindings_application_created",
        "application_field_bindings",
        ["application_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_field_bindings_application_created",
        table_name="application_field_bindings",
    )
    op.drop_index(
        "ix_application_field_bindings_application_answer_id",
        table_name="application_field_bindings",
    )
    op.drop_index(
        "ix_application_field_bindings_application_id",
        table_name="application_field_bindings",
    )
    op.drop_table("application_field_bindings")
