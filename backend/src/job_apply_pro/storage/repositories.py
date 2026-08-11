from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_apply_pro.domain.applications import Application, ApplicationCreate
from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionResult,
    BrowserEngine,
    BrowserObservation,
    BrowserSessionRecord,
    BrowserSessionSnapshot,
    BrowserSessionState,
)
from job_apply_pro.domain.candidate import CandidateBackup, CandidateStatus
from job_apply_pro.domain.checkpoints import EncryptedCheckpointRecord
from job_apply_pro.domain.jobs import Job, JobCreate
from job_apply_pro.domain.portals import (
    PortalCapability,
    PortalFieldMapping,
    PortalKind,
    PortalQualification,
    PortalRunSnapshot,
    SubmissionEvidence,
)
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
    BrowserActionRow,
    BrowserSessionRow,
    CandidateProfileRow,
    FitScoreRow,
    JobRequirementRow,
    JobRow,
    PortalRunRow,
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


def _browser_record(row: BrowserSessionRow, action_count: int) -> BrowserSessionRecord:
    observation = (
        BrowserObservation.model_validate(row.last_observation_json)
        if row.last_observation_json is not None
        else None
    )
    return BrowserSessionRecord(
        id=row.id,
        workflow_id=row.workflow_id,
        engine=BrowserEngine(row.engine),
        profile_name=row.profile_name,
        state=BrowserSessionState(row.state),
        current_url=row.current_url,
        allowed_origins=row.allowed_origins_json,
        observation=observation,
        action_count=action_count,
        trace_path=row.trace_path,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
        user_data_dir=row.user_data_dir,
        artifact_dir=row.artifact_dir,
        headless=row.headless,
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

    def find_by_identity(self, source: str, external_id: str) -> Job | None:
        row = self._session.scalar(
            select(JobRow).where(
                JobRow.source == source,
                JobRow.external_id == external_id,
            )
        )
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


class BrowserRuntimeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: BrowserSessionRecord) -> BrowserSessionRecord:
        self._session.add(
            BrowserSessionRow(
                id=record.id,
                workflow_id=record.workflow_id,
                engine=record.engine.value,
                profile_name=record.profile_name,
                user_data_dir=record.user_data_dir,
                artifact_dir=record.artifact_dir,
                headless=record.headless,
                state=record.state.value,
                current_url=record.current_url,
                allowed_origins_json=record.allowed_origins,
                last_observation_json=(
                    record.observation.model_dump(mode="json") if record.observation else None
                ),
                trace_path=record.trace_path,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )
        self._session.commit()
        return record

    def get_record(self, session_id: str) -> BrowserSessionRecord | None:
        row = self._session.get(BrowserSessionRow, session_id)
        if row is None:
            return None
        return _browser_record(row, self._action_count(session_id))

    def list_snapshots(self, workflow_id: str | None = None) -> list[BrowserSessionSnapshot]:
        statement = select(BrowserSessionRow).order_by(BrowserSessionRow.updated_at.desc())
        if workflow_id is not None:
            statement = statement.where(BrowserSessionRow.workflow_id == workflow_id)
        return [
            BrowserSessionSnapshot.model_validate(
                _browser_record(row, self._action_count(row.id)).model_dump()
            )
            for row in self._session.scalars(statement).all()
        ]

    def save_observation(
        self,
        session_id: str,
        state: BrowserSessionState,
        observation: BrowserObservation,
        *,
        trace_path: str | None = None,
    ) -> BrowserSessionRecord:
        row = self._session.get(BrowserSessionRow, session_id)
        if row is None:
            raise LookupError(f"Browser session {session_id} was not found")
        row.state = state.value
        row.current_url = observation.url
        row.last_observation_json = observation.model_dump(mode="json")
        if trace_path is not None:
            row.trace_path = trace_path
        row.updated_at = utc_now()
        self._session.commit()
        return _browser_record(row, self._action_count(session_id))

    def set_state(
        self,
        session_id: str,
        state: BrowserSessionState,
        *,
        trace_path: str | None = None,
    ) -> BrowserSessionRecord:
        row = self._session.get(BrowserSessionRow, session_id)
        if row is None:
            raise LookupError(f"Browser session {session_id} was not found")
        row.state = state.value
        if trace_path is not None:
            row.trace_path = trace_path
        row.updated_at = utc_now()
        self._session.commit()
        return _browser_record(row, self._action_count(session_id))

    def add_action(self, result: BrowserActionResult) -> BrowserActionResult:
        row = self._session.get(BrowserSessionRow, result.session_id)
        if row is None:
            raise LookupError(f"Browser session {result.session_id} was not found")
        try:
            self._session.add(
                BrowserActionRow(
                    id=result.id,
                    session_id=result.session_id,
                    sequence=result.sequence,
                    action_json=result.action.model_dump(mode="json"),
                    verified=result.verified,
                    attempts=result.attempts,
                    observation_json=result.observation.model_dump(mode="json"),
                    error=result.error,
                    created_at=result.created_at,
                )
            )
            row.current_url = result.observation.url
            row.last_observation_json = result.observation.model_dump(mode="json")
            row.updated_at = result.created_at
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return result

    def list_actions(self, session_id: str) -> list[BrowserActionResult]:
        statement = (
            select(BrowserActionRow)
            .where(BrowserActionRow.session_id == session_id)
            .order_by(BrowserActionRow.sequence)
        )
        return [
            BrowserActionResult(
                id=row.id,
                session_id=row.session_id,
                sequence=row.sequence,
                action=BrowserAction.model_validate(row.action_json),
                verified=row.verified,
                attempts=row.attempts,
                observation=BrowserObservation.model_validate(row.observation_json),
                error=row.error,
                created_at=_utc(row.created_at),
            )
            for row in self._session.scalars(statement).all()
        ]

    def next_action_sequence(self, session_id: str) -> int:
        statement = select(func.max(BrowserActionRow.sequence)).where(
            BrowserActionRow.session_id == session_id
        )
        latest = self._session.scalar(statement)
        return 1 if latest is None else latest + 1

    def _action_count(self, session_id: str) -> int:
        statement = select(func.count(BrowserActionRow.id)).where(
            BrowserActionRow.session_id == session_id
        )
        return int(self._session.scalar(statement) or 0)


def _portal_run(row: PortalRunRow) -> PortalRunSnapshot:
    return PortalRunSnapshot(
        id=row.id,
        portal=PortalKind(row.portal),
        capabilities=[PortalCapability(value) for value in row.capabilities_json],
        workflow_id=row.workflow_id,
        application_id=row.application_id,
        browser_session_id=row.browser_session_id,
        profile_id=row.profile_id,
        job_id=row.job_id,
        state=WorkflowState(row.state),
        portal_origin=row.portal_origin,
        query=row.query,
        deduplicated=row.deduplicated,
        qualification=PortalQualification.model_validate(row.qualification_json),
        selected_document_version_id=row.selected_document_version_id,
        field_mappings=[
            PortalFieldMapping.model_validate(value) for value in row.field_mappings_json
        ],
        review_fingerprint=row.review_fingerprint,
        submission_evidence=(
            SubmissionEvidence.model_validate(row.submission_evidence_json)
            if row.submission_evidence_json is not None
            else None
        ),
        trace_path=row.trace_path,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


class PortalRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, run: PortalRunSnapshot) -> PortalRunSnapshot:
        row = self._session.get(PortalRunRow, run.id)
        values = {
            "portal": run.portal.value,
            "capabilities_json": [value.value for value in run.capabilities],
            "workflow_id": run.workflow_id,
            "application_id": run.application_id,
            "browser_session_id": run.browser_session_id,
            "profile_id": run.profile_id,
            "job_id": run.job_id,
            "state": run.state.value,
            "portal_origin": run.portal_origin,
            "query": run.query,
            "deduplicated": run.deduplicated,
            "qualification_json": run.qualification.model_dump(mode="json"),
            "selected_document_version_id": run.selected_document_version_id,
            "field_mappings_json": [value.model_dump(mode="json") for value in run.field_mappings],
            "review_fingerprint": run.review_fingerprint,
            "submission_evidence_json": (
                run.submission_evidence.model_dump(mode="json")
                if run.submission_evidence is not None
                else None
            ),
            "trace_path": run.trace_path,
            "updated_at": run.updated_at,
        }
        if row is None:
            row = PortalRunRow(id=run.id, created_at=run.created_at, **values)
            self._session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self._session.commit()
        return run

    def get(self, run_id: str) -> PortalRunSnapshot | None:
        row = self._session.get(PortalRunRow, run_id)
        return _portal_run(row) if row is not None else None

    def list_runs(self) -> list[PortalRunSnapshot]:
        rows = self._session.scalars(
            select(PortalRunRow).order_by(PortalRunRow.updated_at.desc())
        ).all()
        return [_portal_run(row) for row in rows]

    def add_job_analysis(
        self,
        *,
        job_id: str,
        profile_id: str,
        requirements: list[str],
        score: float,
        explanation: dict[str, object],
    ) -> None:
        now = utc_now()
        existing_requirements = self._session.scalar(
            select(func.count(JobRequirementRow.id)).where(JobRequirementRow.job_id == job_id)
        )
        if not existing_requirements:
            self._session.add_all(
                [
                    JobRequirementRow(
                        id=str(uuid4()),
                        job_id=job_id,
                        category="reference-ats",
                        text=requirement,
                        required=True,
                        evidence_json={"source": "reference-ats-detail"},
                    )
                    for requirement in requirements
                ]
            )
        self._session.add(
            FitScoreRow(
                id=str(uuid4()),
                job_id=job_id,
                profile_id=profile_id,
                score=score,
                explanation_json=explanation,
                model_version="deterministic-reference-v1",
                created_at=now,
            )
        )
        self._session.commit()


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
