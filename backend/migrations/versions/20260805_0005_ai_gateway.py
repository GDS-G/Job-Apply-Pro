"""Add governed AI Gateway invocation and encrypted cache persistence.

Revision ID: 20260805_0005
Revises: 20260805_0004
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0005"
down_revision: str | None = "20260805_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("model_invocations") as batch:
        batch.add_column(sa.Column("profile_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column("cache_key", sa.String(length=64), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column(
                "classification",
                sa.String(length=40),
                nullable=False,
                server_default="ROUTINE",
            )
        )
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("route_json", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("error_code", sa.String(length=80), nullable=True))
        batch.add_column(
            sa.Column(
                "completed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch.create_index("ix_model_invocations_profile_id", ["profile_id"])
        batch.create_index("ix_model_invocations_cache_key", ["cache_key"])

    op.create_table(
        "ai_cache",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=True),
        sa.Column("classification", sa.String(length=40), nullable=False),
        sa.Column("encrypted_response", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_ai_cache_profile_id", "ai_cache", ["profile_id"])
    op.create_index("ix_ai_cache_expires_at", "ai_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_cache_expires_at", table_name="ai_cache")
    op.drop_index("ix_ai_cache_profile_id", table_name="ai_cache")
    op.drop_table("ai_cache")
    with op.batch_alter_table("model_invocations") as batch:
        batch.drop_index("ix_model_invocations_cache_key")
        batch.drop_index("ix_model_invocations_profile_id")
        for column in (
            "completed_at",
            "error_code",
            "latency_ms",
            "route_json",
            "attempts",
            "classification",
            "cache_key",
            "profile_id",
        ):
            batch.drop_column(column)
