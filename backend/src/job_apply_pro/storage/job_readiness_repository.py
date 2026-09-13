"""Own one SQLite write transaction for review proof and legitimate milestones."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from job_apply_pro.domain.applications import Application
from job_apply_pro.domain.job_discovery import GreenhouseJobReview
from job_apply_pro.domain.job_readiness import (
    JobReadinessError,
    QualificationReview,
    ReadinessSelectionReview,
    RequirementsReview,
    ReviewKind,
)
from job_apply_pro.domain.jobs import Job
from job_apply_pro.domain.knowledge import CandidateClaim, DocumentSelectionAudit
from job_apply_pro.domain.workflow import (
    TransitionCommand,
    VerificationResult,
    WorkflowState,
    utc_now,
    validate_transition,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.storage.models import (
    ApplicationRow,
    DocumentRow,
    DocumentSelectionAuditRow,
    DocumentVersionRow,
    EvidenceSourceRow,
    JobDiscoverySnapshotRow,
    JobReadinessReviewRow,
    WorkflowEventRow,
)
from job_apply_pro.storage.repositories import ApplicationRepository, JobRepository

ReviewRecord = RequirementsReview | QualificationReview | ReadinessSelectionReview
EARLY_STATES = (
    WorkflowState.DEDUPLICATED,
    WorkflowState.SCORED,
    WorkflowState.ELIGIBILITY_CHECKED,
    WorkflowState.DOCUMENTS_SELECTED,
)


class JobReadinessRepository:
    def __init__(self, session: Session, cipher: SensitiveDataCipher) -> None:
        self._session = session
        self._cipher = cipher

    def application_job(self, application_id: str) -> tuple[Application, Job]:
        application = ApplicationRepository(self._session).get(application_id)
        if application is None:
            raise JobReadinessError("Application is unavailable; select an existing application")
        job = JobRepository(self._session).get(application.job_id)
        if job is None:
            raise JobReadinessError("Saved job is unavailable")
        return application, job

    def source(self, job_id: str) -> GreenhouseJobReview | None:
        row = self._session.get(JobDiscoverySnapshotRow, job_id)
        if row is None:
            return None
        review = GreenhouseJobReview.model_validate(row.review_json)
        if row.review_fingerprint != review.review_fingerprint:
            raise JobReadinessError("Saved source identity is inconsistent; readiness is blocked")
        return review

    def claim_source(self, claim: CandidateClaim) -> dict[str, object] | None:
        if claim.evidence_source_id is None:
            return None
        source = self._session.get(EvidenceSourceRow, claim.evidence_source_id)
        if source is None or source.profile_id != claim.profile_id:
            return None
        result: dict[str, object] = {
            "id": source.id,
            "profile_id": source.profile_id,
            "source_type": source.source_type,
            "source_label": source.source_label,
            "source_uri": source.source_uri,
            "content_hash": source.content_hash,
            "document_version_id": source.document_version_id,
        }
        if source.document_version_id is not None:
            version = self._session.get(DocumentVersionRow, source.document_version_id)
            document = self._session.get(DocumentRow, version.document_id) if version else None
            if (
                version is None
                or document is None
                or document.profile_id != claim.profile_id
                or document.archived
            ):
                return None
            if source.content_hash != version.sha256:
                return None
            result["document_version"] = {
                "id": version.id,
                "sha256": version.sha256,
                "parser_version": version.parser_version,
                "encrypted_extraction": version.encrypted_extraction,
            }
        return result

    def latest(self, application_id: str, kind: ReviewKind) -> ReviewRecord | None:
        row = self._session.scalar(
            select(JobReadinessReviewRow)
            .where(
                JobReadinessReviewRow.application_id == application_id,
                JobReadinessReviewRow.kind == kind,
            )
            .order_by(JobReadinessReviewRow.revision.desc())
            .limit(1)
        )
        return self._read(row) if row else None

    def existing(
        self, application_id: str, kind: ReviewKind, request_fingerprint: str
    ) -> ReviewRecord | None:
        row = self._session.scalar(
            select(JobReadinessReviewRow).where(
                JobReadinessReviewRow.application_id == application_id,
                JobReadinessReviewRow.kind == kind,
                JobReadinessReviewRow.request_fingerprint == request_fingerprint,
            )
        )
        return self._read(row) if row else None

    def _read(self, row: JobReadinessReviewRow) -> ReviewRecord:
        payload = self._cipher.decrypt_json(
            row.encrypted_payload, context=f"job-readiness:{row.application_id}:{row.id}"
        )
        record: ReviewRecord
        if row.kind == "REQUIREMENTS":
            record = RequirementsReview.model_validate(payload)
        elif row.kind == "QUALIFICATION":
            record = QualificationReview.model_validate(payload)
        elif row.kind == "SELECTION":
            record = ReadinessSelectionReview.model_validate(payload)
        else:
            raise JobReadinessError("Readiness review type is unsupported")
        if (
            record.id != row.id
            or record.application_id != row.application_id
            or record.revision != row.revision
        ):
            raise JobReadinessError("Readiness review identity is inconsistent")
        return record

    def metadata(self, application_id: str, kind: ReviewKind) -> tuple[str, int, datetime]:
        revision = self._session.scalar(
            select(func.max(JobReadinessReviewRow.revision)).where(
                JobReadinessReviewRow.application_id == application_id,
                JobReadinessReviewRow.kind == kind,
            )
        )
        return str(uuid4()), (revision or 0) + 1, utc_now()

    def append(self, kind: ReviewKind, request_fingerprint: str, record: ReviewRecord) -> None:
        self._session.add(
            JobReadinessReviewRow(
                id=record.id,
                application_id=record.application_id,
                kind=kind,
                revision=record.revision,
                request_fingerprint=request_fingerprint,
                encrypted_payload=self._cipher.encrypt_json(
                    record.model_dump(mode="json"),
                    context=f"job-readiness:{record.application_id}:{record.id}",
                ),
                created_at=record.created_at,
            )
        )

    @contextmanager
    def write(self, application_id: str) -> Iterator[None]:
        try:
            # Acquire SQLite's writer reservation before re-reading dependencies.
            # Other cooperating writers cannot change claims/reviews halfway
            # through validation. No generic, individually committing helpers run
            # inside this unit of work.
            result = self._session.connection().execute(
                update(ApplicationRow)
                .where(ApplicationRow.id == application_id)
                .values(updated_at=ApplicationRow.updated_at)
            )
            if result.rowcount != 1:
                raise JobReadinessError("Application is unavailable")
            self._session.expire_all()
            yield
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise JobReadinessError(
                "Readiness changed or is busy; reload and review again"
            ) from None
        except BaseException:
            self._session.rollback()
            raise

    def advance(self, application_id: str, target: WorkflowState, review_id: str) -> None:
        row = self._session.get(ApplicationRow, application_id)
        if row is None or WorkflowState(row.state) not in EARLY_STATES:
            raise JobReadinessError("This workflow is outside local readiness review")
        current = WorkflowState(row.state)
        # Existing events are history, never rewritten or moved backwards. Current
        # effective readiness is independently derived from dependency fingerprints.
        while EARLY_STATES.index(current) < EARLY_STATES.index(target):
            next_state = EARLY_STATES[EARLY_STATES.index(current) + 1]
            command = TransitionCommand(
                current_state=current,
                next_state=next_state,
                actor="reviewed-job-readiness",
                cause=f"Operator-reviewed local evidence persisted in review {review_id}; "
                "no portal action",
                verification=VerificationResult.NOT_REQUIRED
                if next_state is WorkflowState.SCORED
                else VerificationResult.PASSED,
            )
            validate_transition(command)
            sequence = (
                self._session.scalar(
                    select(func.max(WorkflowEventRow.sequence)).where(
                        WorkflowEventRow.workflow_id == row.workflow_id
                    )
                )
                or 0
            )
            self._session.add(
                WorkflowEventRow(
                    id=str(uuid4()),
                    workflow_id=row.workflow_id,
                    sequence=sequence + 1,
                    prior_state=current.value,
                    next_state=next_state.value,
                    actor=command.actor,
                    cause=command.cause,
                    verification=command.verification.value,
                    retry_count=0,
                    occurred_at=utc_now(),
                )
            )
            self._session.flush()
            row.state = next_state.value
            row.updated_at = utc_now()
            current = next_state

    def select_document(self, audit: DocumentSelectionAudit) -> None:
        row = self._session.get(ApplicationRow, audit.application_id)
        if row is None:
            raise JobReadinessError("Application is unavailable")
        row.selected_document_version_id = audit.document_version_id
        row.updated_at = audit.created_at
        self._session.add(
            DocumentSelectionAuditRow(
                id=audit.id,
                application_id=audit.application_id,
                profile_id=audit.profile_id,
                job_id=audit.job_id,
                document_id=audit.document_id,
                document_version_id=audit.document_version_id,
                score=audit.score,
                review_fingerprint=audit.review_fingerprint,
                criteria_json=audit.criteria,
                reasons_json=audit.reasons,
                created_at=audit.created_at,
            )
        )
