from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_apply_pro.domain.applications import Application, ApplicationCreate
from job_apply_pro.domain.candidate import CandidateBackup, CandidateStatus
from job_apply_pro.domain.checkpoints import EncryptedCheckpointRecord
from job_apply_pro.domain.jobs import Job, JobCreate
from job_apply_pro.domain.workbench import WorkflowRunSnapshot
from job_apply_pro.domain.workflow import (
    TransitionCommand,
    VerificationResult,
    WorkflowEvent,
    WorkflowState,
    utc_now,
    validate_transition,
)
from job_apply_pro.storage.models import (
    ApplicationRow,
    CandidateProfileRow,
    JobRow,
    WorkflowCheckpointRow,
    WorkflowEventRow,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _event_from_row(row: WorkflowEventRow) -> WorkflowEvent:
    return WorkflowEvent(
        id=row.id,
        workflow_id=row.workflow_id,
        sequence=row.sequence,
        prior_state=WorkflowState(row.prior_state),
        next_state=WorkflowState(row.next_state),
        actor=row.actor,
        cause=row.cause,
        verification=VerificationResult(row.verification),
        retry_count=row.retry_count,
        occurred_at=_utc(row.occurred_at),
    )


def _event_row(event: WorkflowEvent) -> WorkflowEventRow:
    return WorkflowEventRow(
        id=event.id,
        workflow_id=event.workflow_id,
        sequence=event.sequence,
        prior_state=event.prior_state.value,
        next_state=event.next_state.value,
        actor=event.actor,
        cause=event.cause,
        verification=event.verification.value,
        retry_count=event.retry_count,
        occurred_at=event.occurred_at,
    )


class WorkflowEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def next_sequence(self, workflow_id: str) -> int:
        statement = select(func.max(WorkflowEventRow.sequence)).where(
            WorkflowEventRow.workflow_id == workflow_id
        )
        latest = self._session.scalar(statement)
        return 1 if latest is None else latest + 1

    def add(self, event: WorkflowEvent) -> WorkflowEvent:
        self._session.add(_event_row(event))
        self._session.commit()
        return event

    def list_for_workflow(self, workflow_id: str) -> list[WorkflowEvent]:
        statement = (
            select(WorkflowEventRow)
            .where(WorkflowEventRow.workflow_id == workflow_id)
            .order_by(WorkflowEventRow.sequence)
        )
        rows = self._session.scalars(statement).all()
        return [_event_from_row(row) for row in rows]


class CandidateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_encrypted(self, backup: CandidateBackup) -> CandidateBackup:
        self._session.add(
            CandidateProfileRow(
                id=backup.profile_id,
                display_name=backup.display_name,
                encrypted_contact=backup.encrypted_contact,
                status=backup.status.value,
                created_at=backup.created_at,
                updated_at=backup.updated_at,
            )
        )
        self._session.commit()
        return backup

    def get_encrypted(self, profile_id: str) -> CandidateBackup | None:
        row = self._session.get(CandidateProfileRow, profile_id)
        if row is None:
            return None
        return CandidateBackup(
            profile_id=row.id,
            display_name=row.display_name,
            encrypted_contact=row.encrypted_contact,
            status=CandidateStatus(row.status),
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, command: JobCreate) -> Job:
        job = Job(
            id=str(uuid4()),
            source=command.source,
            external_id=command.external_id,
            employer=command.employer,
            title=command.title,
            location=command.location,
            source_url=str(command.source_url) if command.source_url else None,
            description_hash=command.description_hash,
            discovered_at=utc_now(),
        )
        self._session.add(
            JobRow(
                id=job.id,
                source=job.source,
                external_id=job.external_id,
                employer=job.employer,
                title=job.title,
                location=job.location,
                source_url=job.source_url,
                description_hash=job.description_hash,
                discovered_at=job.discovered_at,
            )
        )
        self._session.commit()
        return job

    def get(self, job_id: str) -> Job | None:
        row = self._session.get(JobRow, job_id)
        if row is None:
            return None
        return Job(
            id=row.id,
            source=row.source,
            external_id=row.external_id,
            employer=row.employer,
            title=row.title,
            location=row.location,
            source_url=row.source_url,
            description_hash=row.description_hash,
            discovered_at=_utc(row.discovered_at),
        )


class ApplicationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, command: ApplicationCreate) -> Application:
        now = utc_now()
        application = Application(
            id=str(uuid4()),
            workflow_id=command.workflow_id,
            profile_id=command.profile_id,
            job_id=command.job_id,
            state=WorkflowState.DISCOVERED,
            selected_document_version_id=command.selected_document_version_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(
            ApplicationRow(
                id=application.id,
                workflow_id=application.workflow_id,
                profile_id=application.profile_id,
                job_id=application.job_id,
                state=application.state.value,
                selected_document_version_id=application.selected_document_version_id,
                created_at=application.created_at,
                updated_at=application.updated_at,
            )
        )
        self._session.commit()
        return application

    def get(self, application_id: str) -> Application | None:
        row = self._session.get(ApplicationRow, application_id)
        if row is None:
            return None
        return Application(
            id=row.id,
            workflow_id=row.workflow_id,
            profile_id=row.profile_id,
            job_id=row.job_id,
            state=WorkflowState(row.state),
            selected_document_version_id=row.selected_document_version_id,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )


class CheckpointRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def next_sequence(self, workflow_id: str) -> int:
        statement = select(func.max(WorkflowCheckpointRow.sequence)).where(
            WorkflowCheckpointRow.workflow_id == workflow_id
        )
        latest = self._session.scalar(statement)
        return 1 if latest is None else latest + 1

    def add_encrypted(self, checkpoint: EncryptedCheckpointRecord) -> EncryptedCheckpointRecord:
        self._session.add(
            WorkflowCheckpointRow(
                id=checkpoint.id,
                workflow_id=checkpoint.workflow_id,
                sequence=checkpoint.sequence,
                state=checkpoint.state.value,
                page_fingerprint=checkpoint.page_fingerprint,
                encrypted_payload=checkpoint.encrypted_payload,
                created_at=checkpoint.created_at,
            )
        )
        self._session.commit()
        return checkpoint

    def latest_encrypted(self, workflow_id: str) -> EncryptedCheckpointRecord | None:
        statement = (
            select(WorkflowCheckpointRow)
            .where(WorkflowCheckpointRow.workflow_id == workflow_id)
            .order_by(WorkflowCheckpointRow.sequence.desc())
            .limit(1)
        )
        row = self._session.scalar(statement)
        if row is None:
            return None
        return EncryptedCheckpointRecord(
            id=row.id,
            workflow_id=row.workflow_id,
            sequence=row.sequence,
            state=WorkflowState(row.state),
            page_fingerprint=row.page_fingerprint,
            encrypted_payload=row.encrypted_payload,
            created_at=_utc(row.created_at),
        )


class WorkbenchRepository:
    _PROGRESS: ClassVar[dict[WorkflowState, int]] = {
        WorkflowState.DISCOVERED: 5,
        WorkflowState.DEDUPLICATED: 15,
        WorkflowState.SCORED: 28,
        WorkflowState.ELIGIBILITY_CHECKED: 40,
        WorkflowState.DOCUMENTS_SELECTED: 52,
        WorkflowState.APPLICATION_OPENED: 64,
        WorkflowState.FORM_MAPPED: 76,
        WorkflowState.ANSWERS_VALIDATED: 88,
        WorkflowState.READY_TO_SUBMIT: 100,
        WorkflowState.USER_TAKEOVER: 50,
        WorkflowState.FAILED_RETRYABLE: 40,
        WorkflowState.FAILED_TERMINAL: 100,
        WorkflowState.CLOSED: 100,
    }

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_snapshot(self, workflow_id: str) -> WorkflowRunSnapshot | None:
        statement = (
            select(ApplicationRow, JobRow, CandidateProfileRow)
            .join(JobRow, JobRow.id == ApplicationRow.job_id)
            .join(CandidateProfileRow, CandidateProfileRow.id == ApplicationRow.profile_id)
            .where(ApplicationRow.workflow_id == workflow_id)
        )
        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        application, job, candidate = row._tuple()
        return self._snapshot(application, job, candidate)

    def list_snapshots(self) -> list[WorkflowRunSnapshot]:
        statement = (
            select(ApplicationRow, JobRow, CandidateProfileRow)
            .join(JobRow, JobRow.id == ApplicationRow.job_id)
            .join(CandidateProfileRow, CandidateProfileRow.id == ApplicationRow.profile_id)
            .order_by(ApplicationRow.updated_at.desc())
        )
        return [self._snapshot(*row._tuple()) for row in self._session.execute(statement).all()]

    def apply_transition(self, workflow_id: str, command: TransitionCommand) -> WorkflowRunSnapshot:
        statement = select(ApplicationRow).where(ApplicationRow.workflow_id == workflow_id)
        application = self._session.scalar(statement)
        if application is None:
            raise LookupError(f"Workflow {workflow_id} was not found")
        current = WorkflowState(application.state)
        if current is not command.current_state:
            message = (
                f"Workflow state changed from {command.current_state} to {current}; "
                "refresh and retry"
            )
            raise ValueError(message)
        validate_transition(command)
        event = WorkflowEvent(
            id=str(uuid4()),
            workflow_id=workflow_id,
            sequence=self._next_sequence(workflow_id),
            prior_state=current,
            next_state=command.next_state,
            actor=command.actor,
            cause=command.cause,
            verification=command.verification,
            retry_count=command.retry_count,
            occurred_at=utc_now(),
        )
        try:
            self._session.add(_event_row(event))
            application.state = command.next_state.value
            application.updated_at = event.occurred_at
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        snapshot = self.get_snapshot(workflow_id)
        if snapshot is None:  # pragma: no cover - protected by the transaction above
            raise LookupError(f"Workflow {workflow_id} was not found")
        return snapshot

    def _next_sequence(self, workflow_id: str) -> int:
        statement = select(func.max(WorkflowEventRow.sequence)).where(
            WorkflowEventRow.workflow_id == workflow_id
        )
        latest = self._session.scalar(statement)
        return 1 if latest is None else latest + 1

    def _snapshot(
        self,
        application: ApplicationRow,
        job: JobRow,
        candidate: CandidateProfileRow,
    ) -> WorkflowRunSnapshot:
        state = WorkflowState(application.state)
        event_statement = (
            select(WorkflowEventRow)
            .where(WorkflowEventRow.workflow_id == application.workflow_id)
            .order_by(WorkflowEventRow.sequence)
        )
        events = [_event_from_row(row) for row in self._session.scalars(event_statement).all()]
        return WorkflowRunSnapshot(
            workflow_id=application.workflow_id,
            application_id=application.id,
            profile_id=application.profile_id,
            candidate_display_name=candidate.display_name,
            employer=job.employer,
            title=job.title,
            state=state,
            progress=self._PROGRESS.get(state, 60),
            updated_at=_utc(application.updated_at),
            events=events,
        )
