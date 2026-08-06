"""Add encrypted communication, calendar, mutation-audit, and follow-up persistence.

Revision ID: 20260805_0008
Revises: 20260805_0007
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0008"
down_revision: str | None = "20260805_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "communication_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_message_id", sa.String(length=500), nullable=False),
        sa.Column("provider_thread_id", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("workflow_id", sa.String(length=100), nullable=True),
        sa.Column("requires_review", sa.Boolean(), nullable=False),
        sa.Column("encrypted_analysis", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_message_id", name="uq_communication_provider_message"
        ),
    )
    op.create_index("ix_communication_records_provider", "communication_records", ["provider"])
    op.create_index(
        "ix_communication_records_provider_thread_id",
        "communication_records",
        ["provider_thread_id"],
    )
    op.create_index("ix_communication_records_category", "communication_records", ["category"])
    op.create_index(
        "ix_communication_records_workflow_id", "communication_records", ["workflow_id"]
    )
    op.create_index("ix_communication_received", "communication_records", ["received_at"])

    op.create_table(
        "outbound_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("analysis_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_thread_id", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("policy", sa.String(length=30), nullable=False),
        sa.Column("document_version_ids_json", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["communication_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbound_drafts_analysis_id", "outbound_drafts", ["analysis_id"])
    op.create_index("ix_outbound_drafts_workflow_id", "outbound_drafts", ["workflow_id"])
    op.create_index("ix_outbound_drafts_fingerprint", "outbound_drafts", ["fingerprint"])
    op.create_index(
        "ix_outbound_drafts_workflow_updated", "outbound_drafts", ["workflow_id", "updated_at"]
    )

    op.create_table(
        "calendar_mutation_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("workflow_id", sa.String(length=100), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calendar_mutation_plans_provider", "calendar_mutation_plans", ["provider"])
    op.create_index(
        "ix_calendar_mutation_plans_workflow_id", "calendar_mutation_plans", ["workflow_id"]
    )
    op.create_index(
        "ix_calendar_mutation_plans_fingerprint", "calendar_mutation_plans", ["fingerprint"]
    )

    op.create_table(
        "communication_mutation_audits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("confirmed_by", sa.String(length=200), nullable=True),
        sa.Column("provider_resource_id", sa.String(length=500), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_communication_mutation_idempotency"),
    )
    op.create_index(
        "ix_communication_mutation_audits_provider",
        "communication_mutation_audits",
        ["provider"],
    )
    op.create_index(
        "ix_communication_mutation_audits_resource_id",
        "communication_mutation_audits",
        ["resource_id"],
    )
    op.create_index(
        "ix_communication_mutation_audits_status",
        "communication_mutation_audits",
        ["status"],
    )
    op.create_index(
        "ix_communication_mutation_status_occurred",
        "communication_mutation_audits",
        ["status", "occurred_at"],
    )

    op.create_table(
        "communication_follow_ups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_communication_follow_up_dedupe"),
    )
    op.create_index(
        "ix_communication_follow_ups_workflow_id", "communication_follow_ups", ["workflow_id"]
    )
    op.create_index("ix_communication_follow_ups_status", "communication_follow_ups", ["status"])
    op.create_index(
        "ix_communication_follow_up_due", "communication_follow_ups", ["status", "due_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_communication_follow_up_due", table_name="communication_follow_ups")
    op.drop_index("ix_communication_follow_ups_status", table_name="communication_follow_ups")
    op.drop_index("ix_communication_follow_ups_workflow_id", table_name="communication_follow_ups")
    op.drop_table("communication_follow_ups")
    op.drop_index(
        "ix_communication_mutation_status_occurred", table_name="communication_mutation_audits"
    )
    op.drop_index(
        "ix_communication_mutation_audits_status", table_name="communication_mutation_audits"
    )
    op.drop_index(
        "ix_communication_mutation_audits_resource_id",
        table_name="communication_mutation_audits",
    )
    op.drop_index(
        "ix_communication_mutation_audits_provider", table_name="communication_mutation_audits"
    )
    op.drop_table("communication_mutation_audits")
    op.drop_index("ix_calendar_mutation_plans_fingerprint", table_name="calendar_mutation_plans")
    op.drop_index("ix_calendar_mutation_plans_workflow_id", table_name="calendar_mutation_plans")
    op.drop_index("ix_calendar_mutation_plans_provider", table_name="calendar_mutation_plans")
    op.drop_table("calendar_mutation_plans")
    op.drop_index("ix_outbound_drafts_workflow_updated", table_name="outbound_drafts")
    op.drop_index("ix_outbound_drafts_fingerprint", table_name="outbound_drafts")
    op.drop_index("ix_outbound_drafts_workflow_id", table_name="outbound_drafts")
    op.drop_index("ix_outbound_drafts_analysis_id", table_name="outbound_drafts")
    op.drop_table("outbound_drafts")
    op.drop_index("ix_communication_received", table_name="communication_records")
    op.drop_index("ix_communication_records_workflow_id", table_name="communication_records")
    op.drop_index("ix_communication_records_category", table_name="communication_records")
    op.drop_index("ix_communication_records_provider_thread_id", table_name="communication_records")
    op.drop_index("ix_communication_records_provider", table_name="communication_records")
    op.drop_table("communication_records")
