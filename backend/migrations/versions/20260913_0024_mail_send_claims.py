"""Atomically reserve one provider send attempt for each immutable mail draft."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0024"
down_revision: str | None = "20260814_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mail_send_claims",
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("audit_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["outbound_drafts.id"]),
        sa.ForeignKeyConstraint(["audit_id"], ["communication_mutation_audits.id"]),
        sa.PrimaryKeyConstraint("draft_id"),
        sa.UniqueConstraint("audit_id"),
    )


def downgrade() -> None:
    op.drop_table("mail_send_claims")
