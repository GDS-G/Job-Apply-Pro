"""Preserve the exact public posting reviewed at local import."""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0025"
down_revision = "20260913_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_discovery_snapshots",
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("review_fingerprint", sa.String(64), nullable=False),
        sa.Column("review_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("job_discovery_snapshots")
