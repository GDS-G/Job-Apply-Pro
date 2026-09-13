"""Scope correspondence identity to its provider-confirmed account."""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0026"
down_revision = "20260913_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing records retain their exact encrypted content and remain unbound.
    # No OAuth account, reply header or trust is inferred during migration.
    with op.batch_alter_table("communication_records") as batch:
        batch.add_column(
            sa.Column("source_account_key", sa.String(64), nullable=False, server_default="0" * 64)
        )
        batch.add_column(
            sa.Column(
                "source_connection_fingerprint",
                sa.String(64),
                nullable=False,
                server_default="0" * 64,
            )
        )
        batch.drop_constraint("uq_communication_provider_message", type_="unique")
        batch.create_unique_constraint(
            "uq_communication_account_message",
            [
                "provider",
                "source_account_key",
                "source_connection_fingerprint",
                "provider_message_id",
            ],
        )


def downgrade() -> None:
    # Never erase modern source provenance or collapse account-scoped records.
    connection = op.get_bind()
    count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM communication_records "
            "WHERE source_account_key != :unbound OR source_connection_fingerprint != :unbound"
        ),
        {"unbound": "0" * 64},
    ).scalar_one()
    if count:
        raise RuntimeError("Source-bound correspondence requires restoring a pre-upgrade backup")
    with op.batch_alter_table("communication_records") as batch:
        batch.drop_constraint("uq_communication_account_message", type_="unique")
        batch.drop_column("source_connection_fingerprint")
        batch.drop_column("source_account_key")
        batch.create_unique_constraint(
            "uq_communication_provider_message", ["provider", "provider_message_id"]
        )
