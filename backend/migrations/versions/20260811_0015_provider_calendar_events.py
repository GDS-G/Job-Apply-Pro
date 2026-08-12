"""Add encrypted provider calendar event snapshots.

Revision ID: 20260811_0015
Revises: 20260811_0014
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0015"
down_revision: str | None = "20260811_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_calendar_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("event_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("binding_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("encrypted_event", sa.Text(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "event_fingerprint", name="uq_provider_calendar_event_fingerprint"
        ),
    )
    op.create_index(
        "ix_provider_calendar_events_binding_fingerprint",
        "provider_calendar_events",
        ["binding_fingerprint"],
        unique=False,
    )
    op.create_index(
        "ix_provider_calendar_events_provider",
        "provider_calendar_events",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_provider_calendar_event_window",
        "provider_calendar_events",
        ["provider", "starts_at", "ends_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_calendar_events_binding_fingerprint",
        table_name="provider_calendar_events",
    )
    op.drop_index("ix_provider_calendar_event_window", table_name="provider_calendar_events")
    op.drop_index("ix_provider_calendar_events_provider", table_name="provider_calendar_events")
    op.drop_table("provider_calendar_events")
