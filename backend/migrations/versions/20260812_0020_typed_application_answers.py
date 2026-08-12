"""Add typed application-answer validation metadata.

Revision ID: 20260812_0020
Revises: 20260812_0019
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0020"
down_revision: str | None = "20260812_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("application_answers") as batch:
        batch.add_column(
            sa.Column(
                "answer_kind", sa.String(length=40), nullable=False, server_default="SHORT_TEXT"
            )
        )
        batch.add_column(
            sa.Column("validation_rules_json", sa.JSON(), nullable=False, server_default="{}")
        )
        batch.create_index("ix_application_answers_answer_kind", ["answer_kind"])


def downgrade() -> None:
    with op.batch_alter_table("application_answers") as batch:
        batch.drop_index("ix_application_answers_answer_kind")
        batch.drop_column("validation_rules_json")
        batch.drop_column("answer_kind")
