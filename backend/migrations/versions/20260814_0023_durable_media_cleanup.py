"""Add encrypted, leased ownership for deletion-only media recovery.

Revision ID: 20260814_0023
Revises: 20260812_0022
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0023"
down_revision: str | None = "20260812_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_media_cleanup",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=80), nullable=False),
        sa.Column("account_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("owner_token", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("encrypted_resource", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_media_cleanup_account",
        "ai_media_cleanup",
        ["account_fingerprint", "state", "provider_id"],
    )
    op.create_index(
        "ix_ai_media_cleanup_recovery",
        "ai_media_cleanup",
        ["state", "lease_until", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_table("ai_media_cleanup")
