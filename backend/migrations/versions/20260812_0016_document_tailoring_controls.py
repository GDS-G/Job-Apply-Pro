"""Add template and ranking provenance to document generation audits.

Revision ID: 20260812_0016
Revises: 20260811_0015
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0016"
down_revision: str | None = "20260811_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("document_generation_audits") as batch:
        batch.add_column(
            sa.Column(
                "template",
                sa.String(length=30),
                nullable=False,
                server_default="PROFESSIONAL",
            )
        )
        batch.add_column(
            sa.Column(
                "ranking_mode",
                sa.String(length=30),
                nullable=False,
                server_default="DETERMINISTIC",
            )
        )
        batch.add_column(
            sa.Column(
                "ranking_method",
                sa.String(length=80),
                nullable=False,
                server_default="DETERMINISTIC_TOKEN_OVERLAP",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("document_generation_audits") as batch:
        batch.drop_column("ranking_method")
        batch.drop_column("ranking_mode")
        batch.drop_column("template")
