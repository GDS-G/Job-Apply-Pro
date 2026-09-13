"""One transaction preserves source identity, immutable review, and local application."""

import hashlib
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from job_apply_pro.domain.job_discovery import SOURCE, GreenhouseImportResult, GreenhouseJobReview
from job_apply_pro.domain.workflow import WorkflowState, utc_now
from job_apply_pro.storage.models import (
    ApplicationRow,
    CandidateProfileRow,
    JobDiscoverySnapshotRow,
    JobRow,
    WorkflowEventRow,
)
from job_apply_pro.storage.repositories import JobRepository, WorkbenchRepository

SAVED_NOTICE = (
    "Public listing saved locally for review. Qualification has not been evaluated. "
    "No candidate information sent and no application submitted."
)
CHANGED_NOTICE = (
    "This posting differs from the previously saved immutable source snapshot. "
    "The existing record is preserved; source refresh/update is not supported in this slice."
)


class GreenhouseImportConflictError(ValueError):
    pass


class GreenhouseDiscoveryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def profile_exists(self, profile_id: str) -> bool:
        return self._session.get(CandidateProfileRow, profile_id) is not None

    def import_reviewed(
        self, profile_id: str, review: GreenhouseJobReview
    ) -> GreenhouseImportResult:
        # Unique job identity and deterministic workflow ID arbitrate concurrent imports.
        # Never use the individually committing generic add methods in this transaction.
        for attempt in range(2):
            try:
                return self._import_owned(profile_id, review)
            except IntegrityError:
                self._session.rollback()
                if attempt:
                    raise GreenhouseImportConflictError(
                        "Local import conflicted; refresh and retry"
                    ) from None
            except SQLAlchemyError:
                self._session.rollback()
                raise GreenhouseImportConflictError(
                    "Local import is unavailable; refresh and retry"
                ) from None
            except Exception:
                self._session.rollback()
                raise
        raise AssertionError("Import retry exhausted")  # pragma: no cover

    def _import_owned(self, profile_id: str, review: GreenhouseJobReview) -> GreenhouseImportResult:
        if not self.profile_exists(profile_id):
            raise GreenhouseImportConflictError("Select an existing local profile before importing")
        identity = f"{review.board_token}:{review.posting_id}"
        workflow_id = "discovery-" + str(uuid5(NAMESPACE_URL, f"{SOURCE}:{identity}:{profile_id}"))
        row = self._session.scalar(
            select(JobRow).where(
                JobRow.source == SOURCE,
                JobRow.external_id == identity,
            )
        )
        now = utc_now()
        if row is not None:
            saved = self._session.get(JobDiscoverySnapshotRow, row.id)
            if saved is None or saved.review_fingerprint != review.review_fingerprint:
                return GreenhouseImportResult(
                    outcome="SOURCE_CHANGED",
                    job=JobRepository(self._session).get(row.id),
                    notice=CHANGED_NOTICE,
                )
        else:
            row = JobRow(
                id=str(uuid4()),
                source=SOURCE,
                external_id=identity,
                employer=review.employer,
                title=review.title,
                location=review.location,
                source_url=review.source_url,
                description_hash=hashlib.sha256(review.description.encode()).hexdigest(),
                discovered_at=now,
            )
            self._session.add(row)
            self._session.flush()
            self._session.add(
                JobDiscoverySnapshotRow(
                    job_id=row.id,
                    review_fingerprint=review.review_fingerprint,
                    review_json=review.model_dump(mode="json"),
                    created_at=now,
                )
            )
        application = self._session.scalar(
            select(ApplicationRow).where(
                ApplicationRow.workflow_id == workflow_id,
            )
        )
        outcome = "EXISTING"
        if application is None:
            outcome = "IMPORTED"
            application = ApplicationRow(
                id=str(uuid4()),
                workflow_id=workflow_id,
                profile_id=profile_id,
                job_id=row.id,
                state=WorkflowState.DEDUPLICATED.value,
                selected_document_version_id=None,
                created_at=now,
                updated_at=now,
            )
            self._session.add(application)
            self._session.add(
                WorkflowEventRow(
                    id=str(uuid4()),
                    workflow_id=workflow_id,
                    sequence=1,
                    prior_state=WorkflowState.DISCOVERED.value,
                    next_state=WorkflowState.DEDUPLICATED.value,
                    actor="greenhouse-public-discovery",
                    cause="User saved the exact public posting after review; "
                    "canonical identity checked. "
                    "Qualification not evaluated; no application opened or submitted.",
                    verification="NOT_REQUIRED",
                    retry_count=0,
                    occurred_at=now,
                )
            )
        elif application.job_id != row.id or application.profile_id != profile_id:
            raise GreenhouseImportConflictError("Local import identity conflicted")
        self._session.commit()
        job = JobRepository(self._session).get(row.id)
        workflow = WorkbenchRepository(self._session).get_snapshot(workflow_id)
        if job is None or workflow is None:
            raise GreenhouseImportConflictError("Local import result is unavailable")
        return GreenhouseImportResult.model_validate(
            {
                "outcome": outcome,
                "job": job,
                "workflow": workflow,
                "notice": SAVED_NOTICE,
            }
        )
