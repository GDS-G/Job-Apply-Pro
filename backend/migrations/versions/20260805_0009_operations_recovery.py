"""Add encrypted backup, schedule, and restore-plan persistence.

Revision ID: 20260805_0009
Revises: 20260805_0008
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0009"
down_revision: str | None = "20260805_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_manifests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("archive_path", sa.Text(), nullable=False),
        sa.Column("archive_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backup_manifests_status", "backup_manifests", ["status"])
    op.create_index(
        "ix_backup_manifests_status_created", "backup_manifests", ["status", "created_at"]
    )
    op.create_table(
        "backup_schedules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("categories_json", sa.JSON(), nullable=False),
        sa.Column("interval_hours", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backup_schedules_enabled", "backup_schedules", ["enabled"])
    op.create_index("ix_backup_schedules_next_run_at", "backup_schedules", ["next_run_at"])
    op.create_table(
        "restore_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("backup_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["backup_id"], ["backup_manifests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_restore_plans_backup_id", "restore_plans", ["backup_id"])
    op.create_index("ix_restore_plans_status", "restore_plans", ["status"])


def downgrade() -> None:
    op.drop_index("ix_restore_plans_status", table_name="restore_plans")
    op.drop_index("ix_restore_plans_backup_id", table_name="restore_plans")
    op.drop_table("restore_plans")
    op.drop_index("ix_backup_schedules_next_run_at", table_name="backup_schedules")
    op.drop_index("ix_backup_schedules_enabled", table_name="backup_schedules")
    op.drop_table("backup_schedules")
    op.drop_index("ix_backup_manifests_status_created", table_name="backup_manifests")
    op.drop_index("ix_backup_manifests_status", table_name="backup_manifests")
    op.drop_table("backup_manifests")
