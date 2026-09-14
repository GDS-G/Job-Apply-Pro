"""Reserve one provider mutation attempt for each immutable calendar plan."""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0028"
down_revision = "20260913_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    invalid_plan = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM calendar_mutation_plans
            WHERE kind NOT IN ('CREATE_CALENDAR_EVENT', 'UPDATE_CALENDAR_EVENT')
               OR provider NOT IN ('GOOGLE_CALENDAR', 'OUTLOOK_CALENDAR')
            LIMIT 1
            """
        )
    ).first()
    invalid = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM communication_mutation_audits AS audit
            LEFT JOIN calendar_mutation_plans AS plan ON plan.id = audit.resource_id
            WHERE audit.kind IN ('CREATE_CALENDAR_EVENT', 'UPDATE_CALENDAR_EVENT')
              AND (plan.id IS NULL
                   OR plan.provider NOT IN ('GOOGLE_CALENDAR', 'OUTLOOK_CALENDAR')
                   OR audit.provider NOT IN ('GOOGLE_CALENDAR', 'OUTLOOK_CALENDAR')
                   OR audit.provider != plan.provider
                   OR audit.kind != plan.kind
                   OR audit.fingerprint != plan.fingerprint
                   OR audit.status NOT IN ('PLANNED', 'CONFIRMED', 'FAILED', 'UNCERTAIN')
                   OR (audit.status = 'PLANNED'
                       AND (audit.provider_resource_id IS NOT NULL
                            OR audit.error_code IS NOT NULL))
                   OR (audit.status = 'CONFIRMED'
                       AND (audit.provider_resource_id IS NULL
                            OR audit.provider_resource_id = ''
                            OR length(audit.provider_resource_id) > 500
                            OR audit.provider_resource_id GLOB '*[^!-~]*'
                            OR audit.error_code IS NOT NULL))
                   OR (audit.status IN ('FAILED', 'UNCERTAIN')
                       AND (audit.provider_resource_id IS NOT NULL
                            OR audit.error_code IS NULL
                            OR audit.error_code = ''
                            OR length(audit.error_code) > 100
                            OR audit.error_code GLOB '*[^!-~]*')))
            LIMIT 1
            """
        )
    ).first()
    if invalid_plan is not None or invalid is not None:
        raise RuntimeError("Calendar attempt history is inconsistent; migration was not applied")
    op.create_table(
        "calendar_mutation_claims",
        sa.Column("plan_id", sa.String(36), nullable=False),
        sa.Column("audit_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["calendar_mutation_plans.id"]),
        sa.ForeignKeyConstraint(["audit_id"], ["communication_mutation_audits.id"]),
        sa.PrimaryKeyConstraint("plan_id"),
        sa.UniqueConstraint("audit_id"),
    )
    # Retain all legacy attempts, regardless of outcome. Only add a claim for
    # an existing plan, choosing the same stable oldest audit as the repository.
    # No encrypted plan payload or legacy audit identity/status is rewritten.
    op.execute(
        sa.text(
            """
            INSERT INTO calendar_mutation_claims (plan_id, audit_id)
            SELECT plan.id, audit.id
            FROM calendar_mutation_plans AS plan
            JOIN communication_mutation_audits AS audit
              ON audit.resource_id = plan.id
             AND audit.provider = plan.provider
             AND audit.kind = plan.kind
             AND audit.fingerprint = plan.fingerprint
            WHERE audit.kind IN ('CREATE_CALENDAR_EVENT', 'UPDATE_CALENDAR_EVENT')
              AND NOT EXISTS (
                  SELECT 1 FROM communication_mutation_audits AS earlier
                  WHERE earlier.resource_id = plan.id
                    AND earlier.provider = plan.provider
                    AND earlier.kind = plan.kind
                    AND earlier.fingerprint = plan.fingerprint
                    AND (earlier.occurred_at < audit.occurred_at
                         OR (earlier.occurred_at = audit.occurred_at AND earlier.id < audit.id))
              )
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    claims = connection.execute(sa.text("SELECT 1 FROM calendar_mutation_claims LIMIT 1")).first()
    attempts = connection.execute(
        sa.text(
            "SELECT 1 FROM communication_mutation_audits "
            "WHERE kind IN ('CREATE_CALENDAR_EVENT', 'UPDATE_CALENDAR_EVENT') LIMIT 1"
        )
    ).first()
    plans = connection.execute(sa.text("SELECT 1 FROM calendar_mutation_plans LIMIT 1")).first()
    if claims is not None or attempts is not None or plans is not None:
        raise RuntimeError(
            "Calendar attempt history prevents downgrade; preserve the schema and records"
        )
    op.drop_table("calendar_mutation_claims")
