"""Add durable admission for browser and AI external effects."""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0029"
down_revision = "20260913_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_effect_operations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("claim_fingerprint", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("subject_type", sa.String(40), nullable=False),
        sa.Column("subject_id", sa.String(200), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_reference", sa.String(200), nullable=True),
        sa.Column("result_fingerprint", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_fingerprint", name="uq_external_effect_operation_claim"),
    )
    op.create_index(
        "ix_external_effect_operations_kind",
        "external_effect_operations",
        ["kind"],
    )
    op.create_index(
        "ix_external_effect_operations_status",
        "external_effect_operations",
        ["status"],
    )
    op.create_index(
        "ix_external_effect_operation_subject",
        "external_effect_operations",
        ["subject_type", "subject_id", "created_at"],
    )
    op.create_index(
        "ix_external_effect_operation_recovery",
        "external_effect_operations",
        ["status", "updated_at"],
    )
    op.create_table(
        "external_effect_attempts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(200), nullable=False),
        sa.Column("target_code", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("native_key_fingerprint", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_reference", sa.String(200), nullable=True),
        sa.Column("result_fingerprint", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_micros", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["operation_id"], ["external_effect_operations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", "sequence", name="uq_external_effect_attempt_sequence"),
    )
    op.create_index(
        "ix_external_effect_attempts_operation_id",
        "external_effect_attempts",
        ["operation_id"],
    )
    op.create_index(
        "ix_external_effect_attempts_status",
        "external_effect_attempts",
        ["status"],
    )
    op.create_index(
        "ix_external_effect_attempt_recovery",
        "external_effect_attempts",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    operations = connection.execute(
        sa.text("SELECT 1 FROM external_effect_operations LIMIT 1")
    ).first()
    attempts = connection.execute(sa.text("SELECT 1 FROM external_effect_attempts LIMIT 1")).first()
    if operations is not None or attempts is not None:
        raise RuntimeError(
            "External-effect history prevents downgrade; preserve the schema and records"
        )
    op.drop_index("ix_external_effect_attempt_recovery", table_name="external_effect_attempts")
    op.drop_index("ix_external_effect_attempts_status", table_name="external_effect_attempts")
    op.drop_index("ix_external_effect_attempts_operation_id", table_name="external_effect_attempts")
    op.drop_table("external_effect_attempts")
    op.drop_index("ix_external_effect_operation_recovery", table_name="external_effect_operations")
    op.drop_index("ix_external_effect_operation_subject", table_name="external_effect_operations")
    op.drop_index("ix_external_effect_operations_status", table_name="external_effect_operations")
    op.drop_index("ix_external_effect_operations_kind", table_name="external_effect_operations")
    op.drop_table("external_effect_operations")
