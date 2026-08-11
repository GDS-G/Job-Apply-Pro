from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.domain.operations import (
    ApplicationMetrics,
    ApplicationReportRow,
    BackupCategory,
    BackupManifest,
    BackupSchedule,
    ModelCostMetrics,
    RestorePlan,
)
from job_apply_pro.storage.models import (
    ApplicationRow,
    BackupManifestRow,
    BackupScheduleRow,
    CommunicationRecordRow,
    JobRow,
    ModelInvocationRow,
    PortalRunRow,
    RestorePlanRow,
    WorkflowEventRow,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class OperationsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_backup(self, manifest: BackupManifest) -> BackupManifest:
        row = self._session.get(BackupManifestRow, manifest.id)
        values = {
            "status": manifest.status.value,
            "archive_path": manifest.archive_path,
            "archive_sha256": manifest.archive_sha256,
            "manifest_json": manifest.model_dump(mode="json"),
            "verified_at": manifest.verified_at,
        }
        if row is None:
            row = BackupManifestRow(id=manifest.id, created_at=manifest.created_at, **values)
            self._session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self._session.commit()
        return manifest

    def get_backup(self, backup_id: str) -> BackupManifest | None:
        row = self._session.get(BackupManifestRow, backup_id)
        return BackupManifest.model_validate(row.manifest_json) if row else None

    def list_backups(self) -> list[BackupManifest]:
        rows = self._session.scalars(
            select(BackupManifestRow).order_by(BackupManifestRow.created_at.desc())
        ).all()
        return [BackupManifest.model_validate(row.manifest_json) for row in rows]

    def save_schedule(self, schedule: BackupSchedule) -> BackupSchedule:
        row = self._session.get(BackupScheduleRow, schedule.id)
        values = {
            "label": schedule.label,
            "categories_json": [value.value for value in schedule.categories],
            "interval_hours": schedule.interval_hours,
            "enabled": schedule.enabled,
            "next_run_at": schedule.next_run_at,
            "last_run_at": schedule.last_run_at,
            "updated_at": schedule.updated_at,
        }
        if row is None:
            row = BackupScheduleRow(id=schedule.id, created_at=schedule.created_at, **values)
            self._session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self._session.commit()
        return schedule

    def list_schedules(self) -> list[BackupSchedule]:
        rows = self._session.scalars(
            select(BackupScheduleRow).order_by(BackupScheduleRow.next_run_at)
        ).all()
        return [
            BackupSchedule(
                id=row.id,
                label=row.label,
                categories={BackupCategory(value) for value in row.categories_json},
                interval_hours=row.interval_hours,
                enabled=row.enabled,
                next_run_at=_utc(row.next_run_at),
                last_run_at=_utc(row.last_run_at) if row.last_run_at else None,
                created_at=_utc(row.created_at),
                updated_at=_utc(row.updated_at),
            )
            for row in rows
        ]

    def save_restore_plan(self, plan: RestorePlan) -> RestorePlan:
        row = self._session.get(RestorePlanRow, plan.id)
        if row is None:
            row = RestorePlanRow(
                id=plan.id,
                backup_id=plan.backup_id,
                status=plan.status.value,
                plan_json=plan.model_dump(mode="json"),
                created_at=plan.created_at,
                applied_at=plan.applied_at,
            )
            self._session.add(row)
        else:
            row.status = plan.status.value
            row.plan_json = plan.model_dump(mode="json")
            row.applied_at = plan.applied_at
        self._session.commit()
        return plan

    def get_restore_plan(self, plan_id: str) -> RestorePlan | None:
        row = self._session.get(RestorePlanRow, plan_id)
        return RestorePlan.model_validate(row.plan_json) if row else None

    def application_metrics(self) -> ApplicationMetrics:
        applications = list(self._session.scalars(select(ApplicationRow)).all())
        events = list(self._session.scalars(select(WorkflowEventRow)).all())
        communications = list(self._session.scalars(select(CommunicationRecordRow)).all())
        portals = list(self._session.scalars(select(PortalRunRow)).all())
        return ApplicationMetrics(
            jobs_discovered=len(list(self._session.scalars(select(JobRow)).all())),
            applications_total=len(applications),
            submission_attempted=sum(
                event.next_state == "SUBMISSION_ATTEMPTED" for event in events
            ),
            submission_confirmed=sum(
                event.next_state == "SUBMISSION_CONFIRMED" for event in events
            ),
            tracking_active=sum(row.state == "TRACKING_ACTIVE" for row in applications),
            failed=sum(row.state.startswith("FAILED_") for row in applications),
            duplicated=sum(row.deduplicated for row in portals),
            interviews_received=sum(row.category == "INTERVIEW_REQUEST" for row in communications),
            offers_received=sum(row.category == "OFFER" for row in communications),
            recruiter_messages=sum(
                row.category in {"RECRUITER_INQUIRY", "SCREENING_REQUEST"} for row in communications
            ),
        )

    def model_metrics(self) -> ModelCostMetrics:
        rows = list(self._session.scalars(select(ModelInvocationRow)).all())
        providers: dict[str, int] = {}
        for row in rows:
            providers[row.provider] = providers.get(row.provider, 0) + 1
        return ModelCostMetrics(
            invocations=len(rows),
            successful=sum(row.status == "COMPLETED" for row in rows),
            failed=sum(row.status == "FAILED" for row in rows),
            input_tokens=sum(row.input_tokens for row in rows),
            output_tokens=sum(row.output_tokens for row in rows),
            cost_micros=sum(row.cost_micros for row in rows),
            average_latency_ms=(sum(row.latency_ms for row in rows) / len(rows) if rows else 0),
            by_provider=providers,
        )

    def portal_run_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._session.scalars(select(PortalRunRow)).all():
            counts[row.portal] = counts.get(row.portal, 0) + 1
        return counts

    def application_report(self) -> list[ApplicationReportRow]:
        event_states: dict[str, set[str]] = {}
        for event in self._session.scalars(select(WorkflowEventRow)).all():
            event_states.setdefault(event.workflow_id, set()).add(event.next_state)
        statement = (
            select(ApplicationRow, JobRow)
            .join(JobRow, JobRow.id == ApplicationRow.job_id)
            .order_by(ApplicationRow.updated_at.desc())
        )
        return [
            ApplicationReportRow(
                workflow_id=application.workflow_id,
                employer=job.employer,
                title=job.title,
                state=application.state,
                submission_attempted=(
                    "SUBMISSION_ATTEMPTED" in event_states.get(application.workflow_id, set())
                ),
                submission_confirmed=(
                    "SUBMISSION_CONFIRMED" in event_states.get(application.workflow_id, set())
                ),
                updated_at=_utc(application.updated_at),
            )
            for application, job in self._session.execute(statement).all()
        ]
