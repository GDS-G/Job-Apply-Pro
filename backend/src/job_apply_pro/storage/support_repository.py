from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_apply_pro.domain.support import (
    QueueHealth,
    RecoveryHealth,
    SanitizedErrorSummary,
    SessionHealth,
    TraceDiagnostic,
    WorkflowDiagnostic,
)
from job_apply_pro.storage.models import (
    ApplicationRow,
    BrowserActionRow,
    BrowserSessionRow,
    ErrorRecordRow,
    WorkflowCheckpointRow,
    WorkflowEventRow,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class SupportRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def queue_health(self) -> QueueHealth:
        states = list(self._session.scalars(select(ApplicationRow.state)).all())
        terminal_states = {"CLOSED", "FAILED_TERMINAL"}
        return QueueHealth(
            total=len(states),
            active=sum(state not in terminal_states for state in states),
            retryable=sum(state == "FAILED_RETRYABLE" for state in states),
            terminal=sum(state in terminal_states for state in states),
        )

    def recovery_health(self) -> RecoveryHealth:
        retried = list(
            self._session.scalars(
                select(BrowserActionRow).where(BrowserActionRow.attempts > 1)
            ).all()
        )
        recovered = sum(row.verified for row in retried)
        checkpoint_count = self._session.scalar(select(func.count(WorkflowCheckpointRow.id))) or 0
        return RecoveryHealth(
            retried_actions=len(retried),
            recovered_actions=recovered,
            recovery_rate=(recovered / len(retried) if retried else 0),
            checkpoint_count=checkpoint_count,
        )

    def session_health(self) -> SessionHealth:
        states = list(self._session.scalars(select(BrowserSessionRow.state)).all())
        return SessionHealth(
            active=sum(state == "ACTIVE" for state in states),
            takeover=sum(state == "USER_TAKEOVER" for state in states),
            stopped=sum(state == "STOPPED" for state in states),
            failed=sum(state == "FAILED" for state in states),
        )

    def workflows(self) -> list[WorkflowDiagnostic]:
        count_rows = self._session.execute(
            select(WorkflowEventRow.workflow_id, func.count(WorkflowEventRow.id)).group_by(
                WorkflowEventRow.workflow_id
            )
        ).all()
        event_counts: dict[str, int] = {workflow_id: count for workflow_id, count in count_rows}
        rows = self._session.scalars(
            select(ApplicationRow).order_by(ApplicationRow.updated_at.desc()).limit(100)
        ).all()
        return [
            WorkflowDiagnostic(
                workflow_id=row.workflow_id,
                state=row.state,
                event_count=event_counts.get(row.workflow_id, 0),
                updated_at=_utc(row.updated_at),
            )
            for row in rows
        ]

    def sanitized_errors(self) -> list[SanitizedErrorSummary]:
        rows = self._session.scalars(
            select(ErrorRecordRow).order_by(ErrorRecordRow.created_at.desc()).limit(50)
        ).all()
        return [
            SanitizedErrorSummary(
                classification=row.classification,
                component=row.component,
                action=row.action,
                retry_count=row.retry_count,
                context_keys=sorted(row.sanitized_context_json),
                created_at=_utc(row.created_at),
            )
            for row in rows
        ]

    def traces(self) -> list[TraceDiagnostic]:
        rows = self._session.scalars(
            select(BrowserSessionRow)
            .where(BrowserSessionRow.trace_path.is_not(None))
            .order_by(BrowserSessionRow.updated_at.desc())
            .limit(20)
        ).all()
        traces: list[TraceDiagnostic] = []
        for row in rows:
            path = Path(row.trace_path or "")
            available = path.is_file()
            traces.append(
                TraceDiagnostic(
                    workflow_id=row.workflow_id,
                    file_name=path.name,
                    size_bytes=path.stat().st_size if available else 0,
                    available=available,
                )
            )
        return traces
