"""Add encrypted OAuth credentials and one-time PKCE authorization sessions.

Revision ID: 20260811_0010
Revises: 20260805_0009
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0010"
down_revision: str | None = "20260805_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_credentials",
        sa.Column("credential_reference", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("encrypted_token_set", sa.Text(), nullable=False),
        sa.Column("granted_scopes_json", sa.JSON(), nullable=False),
        sa.Column("account_hint", sa.String(length=200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("credential_reference"),
        sa.UniqueConstraint("provider"),
    )
    op.create_index("ix_oauth_credentials_provider", "oauth_credentials", ["provider"])

    op.create_table(
        "oauth_authorization_sessions",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("client_id", sa.String(length=500), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("requested_scopes_json", sa.JSON(), nullable=False),
        sa.Column("encrypted_code_verifier", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("state_hash"),
    )
    op.create_index(
        "ix_oauth_authorization_sessions_provider",
        "oauth_authorization_sessions",
        ["provider"],
    )
    op.create_index(
        "ix_oauth_authorization_sessions_expires_at",
        "oauth_authorization_sessions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_oauth_authorization_sessions_expires_at",
        table_name="oauth_authorization_sessions",
    )
    op.drop_index(
        "ix_oauth_authorization_sessions_provider",
        table_name="oauth_authorization_sessions",
    )
    op.drop_table("oauth_authorization_sessions")
    op.drop_index("ix_oauth_credentials_provider", table_name="oauth_credentials")
    op.drop_table("oauth_credentials")
