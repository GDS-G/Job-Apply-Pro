"""Append-only encrypted operator reviews for real imported job readiness."""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0027"
# Unpublished integration will insert the reserved v059 0026 predecessor.
down_revision = "20260913_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_readiness_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "application_id", "kind", "revision", name="uq_readiness_review_revision"
        ),
        sa.UniqueConstraint(
            "application_id", "kind", "request_fingerprint", name="uq_readiness_review_request"
        ),
    )
    op.create_index(
        "ix_job_readiness_reviews_application_id", "job_readiness_reviews", ["application_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_job_readiness_reviews_application_id", table_name="job_readiness_reviews")
    op.drop_table("job_readiness_reviews")
