from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_apply_pro.domain.applications import Application, ApplicationCreate
from job_apply_pro.domain.candidate import CandidateBackup, CandidateStatus
from job_apply_pro.domain.checkpoints import EncryptedCheckpointRecord
from job_apply_pro.domain.jobs import Job, JobCreate
from job_apply_pro.domain.workflow import VerificationResult, WorkflowEvent, WorkflowState, utc_now
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
        self._session.add(
            WorkflowEventRow(
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
        )
        self._session.commit()
        return event

    def list_for_workflow(self, workflow_id: str) -> list[WorkflowEvent]:
        statement = (
            select(WorkflowEventRow)
            .where(WorkflowEventRow.workflow_id == workflow_id)
            .order_by(WorkflowEventRow.sequence)
        )
        rows = self._session.scalars(statement).all()
        return [
            WorkflowEvent(
                id=row.id,
                workflow_id=row.workflow_id,
                sequence=row.sequence,
                prior_state=WorkflowState(row.prior_state),
                next_state=WorkflowState(row.next_state),
                actor=row.actor,
                cause=row.cause,
                verification=VerificationResult(row.verification),
                retry_count=row.retry_count,
                occurred_at=(
                    row.occurred_at
                    if row.occurred_at.tzinfo is not None
                    else row.occurred_at.replace(tzinfo=UTC)
                ),
            )
            for row in rows
        ]


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
