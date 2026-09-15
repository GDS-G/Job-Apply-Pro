"""Add immutable evidence for reviewed external-effect reconciliation."""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0030"
down_revision = "20260913_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_effect_reconciliations",
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("source_page_fingerprint", sa.String(200), nullable=False),
        sa.Column("evidence_reference", sa.String(200), nullable=True),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=True),
        sa.Column("result_page_fingerprint", sa.String(200), nullable=True),
        sa.Column("policy_version", sa.String(200), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["operation_id"], ["external_effect_operations.id"]),
        sa.ForeignKeyConstraint(["attempt_id"], ["external_effect_attempts.id"]),
        sa.PrimaryKeyConstraint("operation_id"),
        sa.UniqueConstraint("attempt_id", name="uq_external_effect_reconciliation_attempt"),
    )
    op.create_index(
        "ix_external_effect_reconciliations_created",
        "external_effect_reconciliations",
        ["created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    history = connection.execute(
        sa.text("SELECT 1 FROM external_effect_reconciliations LIMIT 1")
    ).first()
    if history is not None:
        raise RuntimeError(
            "External-effect reconciliation history prevents downgrade; preserve the records"
        )
    op.drop_index(
        "ix_external_effect_reconciliations_created",
        table_name="external_effect_reconciliations",
    )
    op.drop_table("external_effect_reconciliations")
