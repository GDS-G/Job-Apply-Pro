"""Add verified application field execution evidence.

Revision ID: 20260812_0022
Revises: 20260812_0021
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0022"
down_revision: str | None = "20260812_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_field_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("application_answer_id", sa.String(length=36), nullable=False),
        sa.Column("answer_revision", sa.Integer(), nullable=False),
        sa.Column("supervised_run_id", sa.String(length=36), nullable=False),
        sa.Column("browser_session_id", sa.String(length=36), nullable=False),
        sa.Column("portal", sa.String(length=80), nullable=False),
        sa.Column("page_fingerprint_before", sa.String(length=200), nullable=False),
        sa.Column("page_fingerprint_after", sa.String(length=200), nullable=False),
        sa.Column("control_key", sa.String(length=200), nullable=False),
        sa.Column("action_kind", sa.String(length=40), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("action_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["application_answer_id"], ["application_answers.id"]),
        sa.ForeignKeyConstraint(["binding_id"], ["application_field_bindings.id"]),
        sa.ForeignKeyConstraint(["browser_session_id"], ["browser_sessions.id"]),
        sa.ForeignKeyConstraint(["supervised_run_id"], ["supervised_portal_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "binding_id",
        "application_id",
        "application_answer_id",
        "supervised_run_id",
        "browser_session_id",
    ):
        op.create_index(
            f"ix_application_field_executions_{column}",
            "application_field_executions",
            [column],
        )
    op.create_index(
        "ix_application_field_executions_application_created",
        "application_field_executions",
        ["application_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("application_field_executions")
