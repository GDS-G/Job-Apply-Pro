from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit
from uuid import uuid4

from job_apply_pro.domain.applications import ApplicationCreate
from job_apply_pro.domain.browser import BrowserAction, BrowserActionResult, BrowserSessionCreate
from job_apply_pro.domain.jobs import JobCreate
from job_apply_pro.domain.knowledge import (
    CandidateDocumentVersionRecord,
    ClaimPermittedUse,
    ClaimVerificationStatus,
    DocumentKind,
)
from job_apply_pro.domain.portals import (
    REFERENCE_ATS_CAPABILITIES,
    PortalKind,
    PortalQualification,
    PortalRunSnapshot,
    ReferencePortalRunCreate,
    SubmissionApproval,
)
from job_apply_pro.domain.workbench import WorkflowRunSnapshot
from job_apply_pro.domain.workflow import (
    TransitionCommand,
    VerificationResult,
    WorkflowState,
    utc_now,
)
from job_apply_pro.portals.reference_ats import PortalContractError, ReferenceAtsAdapter
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.services.browser_runtime import BrowserRuntimeService
from job_apply_pro.services.core import CoreService
from job_apply_pro.storage.repository_contracts import (
    ApplicationRepositoryProtocol,
    CandidateKnowledgeRepositoryProtocol,
    JobRepositoryProtocol,
    PortalRunRepositoryProtocol,
    WorkbenchRepositoryProtocol,
)


class PortalExecutionError(RuntimeError):
    pass


class PortalEligibilityError(PortalExecutionError):
    pass


class PortalApprovalError(PortalExecutionError):
    pass


def _terms(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9+#.]{2,}", value.casefold())
        if token not in {"and", "the", "with", "for", "years", "year"}
    }


class ReferencePortalService:
    def __init__(
        self,
        *,
        core: CoreService,
        jobs: JobRepositoryProtocol,
        applications: ApplicationRepositoryProtocol,
        workbench: WorkbenchRepositoryProtocol,
        knowledge: CandidateKnowledgeRepositoryProtocol,
        runs: PortalRunRepositoryProtocol,
        browser: BrowserRuntimeService,
        cipher: SensitiveDataCipher,
        adapter: ReferenceAtsAdapter | None = None,
    ) -> None:
        self._core = core
        self._jobs = jobs
        self._applications = applications
        self._workbench = workbench
        self._knowledge = knowledge
        self._runs = runs
        self._browser = browser
        self._cipher = cipher
        self._adapter = adapter or ReferenceAtsAdapter()

    def prepare(self, command: ReferencePortalRunCreate) -> PortalRunSnapshot:
        candidate = self._core.get_candidate(command.profile_id)
        document = self._select_document(
            command.profile_id,
            command.query,
            command.preferred_document_version_id,
        )
        postings = self._adapter.discover_jobs(str(command.portal_origin), command.query)
        if not postings:
            raise PortalExecutionError("Reference ATS search returned no jobs")
        posting = postings[0]
        existing = self._jobs.find_by_identity(self._adapter.source, posting.external_id)
        deduplicated = existing is not None
        job = existing or self._jobs.add(
            JobCreate(
                source=self._adapter.source,
                external_id=posting.external_id,
                employer=posting.employer,
                title=posting.title,
                location=posting.location,
                source_url=posting.source_url,
                description_hash=hashlib.sha256(posting.description.encode()).hexdigest(),
            )
        )
        qualification = self._qualify(
            command.profile_id,
            posting.requirements,
            command.minimum_fit_score,
        )
        self._runs.add_job_analysis(
            job_id=job.id,
            profile_id=command.profile_id,
            requirements=posting.requirements,
            score=qualification.score,
            explanation=qualification.model_dump(mode="json"),
        )
        if not qualification.eligible:
            raise PortalEligibilityError(
                f"Fit score {qualification.score:.2f} is below "
                f"the {qualification.threshold:.2f} threshold"
            )

        workflow_id = f"portal-{uuid4()}"
        application = self._applications.add(
            ApplicationCreate(
                workflow_id=workflow_id,
                profile_id=command.profile_id,
                job_id=job.id,
                selected_document_version_id=document.id,
            )
        )
        self._transition(workflow_id, WorkflowState.DEDUPLICATED, "Canonical job identity checked")
        self._transition(workflow_id, WorkflowState.SCORED, "Deterministic fit score persisted")
        self._transition(
            workflow_id,
            WorkflowState.ELIGIBILITY_CHECKED,
            "Minimum qualification threshold passed",
            verification=VerificationResult.PASSED,
        )
        self._transition(
            workflow_id,
            WorkflowState.DOCUMENTS_SELECTED,
            f"Selected approved document version {document.id}",
            verification=VerificationResult.PASSED,
        )

        browser = self._browser.create_session(
            BrowserSessionCreate(
                workflow_id=workflow_id,
                start_url=posting.source_url,
                profile_name=f"reference-{uuid4().hex[:12]}",
                headless=command.headless,
            )
        )
        if browser.observation is None:
            raise PortalExecutionError("Reference ATS job page produced no observation")
        observed_job = self._adapter.extract_job(browser.observation)
        if observed_job.external_id != posting.external_id:
            raise PortalExecutionError("Discovery and browser job identities did not match")
        opened = self._require_verified(
            browser.id,
            self._adapter.click("Apply now", "/application/identity"),
        )
        self._transition(
            workflow_id,
            WorkflowState.APPLICATION_OPENED,
            "Reference ATS application launch was verified",
            verification=VerificationResult.PASSED,
        )
        field_mappings = self._adapter.map_fields(opened.observation)
        if not field_mappings:
            raise PortalExecutionError("Reference ATS identity form exposed no canonical fields")
        self._transition(
            workflow_id,
            WorkflowState.FORM_MAPPED,
            "Canonical identity fields were mapped",
            verification=VerificationResult.PASSED,
        )

        self._require_verified(
            browser.id, self._adapter.fill("Full name", candidate.contact.full_name)
        )
        self._require_verified(browser.id, self._adapter.fill("Email", candidate.contact.email))
        staged_document = self._browser.stage_encrypted_upload(
            browser.id,
            version_id=document.id,
            encrypted_path=document.storage_path,
            file_name=document.file_name,
        )
        try:
            self._require_verified(
                browser.id,
                self._adapter.upload("Resume", staged_document, document.file_name),
            )
        finally:
            self._browser.clear_staged_uploads(browser.id)
        experience = self._require_verified(
            browser.id,
            self._adapter.click("Continue", "/application/experience"),
        )
        field_mappings.extend(self._adapter.map_fields(experience.observation))
        self._require_verified(
            browser.id,
            self._adapter.fill(
                "Years of relevant experience", self._experience_years(command.profile_id)
            ),
        )
        self._require_verified(browser.id, self._adapter.check("Authorized to work"))
        self._require_verified(
            browser.id,
            self._adapter.fill(
                "Why are you interested?",
                self._answer(command.profile_id, posting.employer, posting.title),
            ),
        )
        review = self._require_verified(
            browser.id,
            self._adapter.click("Review application", "/application/review"),
        )
        if review.observation.validation_errors:
            raise PortalExecutionError("Reference ATS review page reported validation errors")
        self._transition(
            workflow_id,
            WorkflowState.ANSWERS_VALIDATED,
            "Required answers and uploaded document were verified",
            verification=VerificationResult.PASSED,
        )
        ready = self._transition(
            workflow_id,
            WorkflowState.READY_TO_SUBMIT,
            "Review fingerprint captured; explicit submission approval required",
            verification=VerificationResult.PASSED,
        )
        now = utc_now()
        run = PortalRunSnapshot(
            id=str(uuid4()),
            portal=PortalKind.REFERENCE_ATS,
            capabilities=list(REFERENCE_ATS_CAPABILITIES),
            workflow_id=workflow_id,
            application_id=application.id,
            browser_session_id=browser.id,
            profile_id=command.profile_id,
            job_id=job.id,
            state=ready.state,
            portal_origin=browser.observation.origin,
            query=command.query,
            deduplicated=deduplicated,
            qualification=qualification,
            selected_document_version_id=document.id,
            field_mappings=field_mappings,
            review_fingerprint=review.observation.page_fingerprint,
            created_at=now,
            updated_at=now,
        )
        return self._runs.save(run)

    def confirm(self, run_id: str, approval: SubmissionApproval) -> PortalRunSnapshot:
        run = self.get(run_id)
        if run.state is not WorkflowState.READY_TO_SUBMIT:
            raise PortalApprovalError(f"Portal run is {run.state}, not ready to submit")
        if approval.confirmation_phrase != "SUBMIT REFERENCE APPLICATION":
            raise PortalApprovalError("The explicit reference submission phrase did not match")
        if approval.review_fingerprint != run.review_fingerprint:
            raise PortalApprovalError("The approved review fingerprint did not match")
        observation = self._browser.observe(run.browser_session_id).observation
        if observation is None or observation.page_fingerprint != run.review_fingerprint:
            raise PortalApprovalError("The review page changed after approval was requested")
        parsed = urlsplit(run.portal_origin)
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise PortalApprovalError("Reference submission is restricted to loopback fixtures")

        result = self._require_verified(run.browser_session_id, self._adapter.submit_action())
        self._transition(
            run.workflow_id,
            WorkflowState.SUBMISSION_ATTEMPTED,
            "Confirmed user approval authorized the loopback submission action",
            verification=VerificationResult.PASSED,
        )
        try:
            evidence = self._adapter.confirmation_evidence(result.observation)
        except PortalContractError:
            self._transition(
                run.workflow_id,
                WorkflowState.SUBMISSION_UNCERTAIN,
                "No approved confirmation signal was observed",
                verification=VerificationResult.UNCERTAIN,
            )
            raise
        self._transition(
            run.workflow_id,
            WorkflowState.SUBMISSION_CONFIRMED,
            f"Verified confirmation signal {evidence.confirmation_code}",
            verification=VerificationResult.PASSED,
        )
        tracked = self._transition(
            run.workflow_id,
            WorkflowState.TRACKING_ACTIVE,
            "Confirmed application entered local tracking",
            verification=VerificationResult.PASSED,
        )
        stopped = self._browser.stop(run.browser_session_id)
        completed = run.model_copy(
            update={
                "state": tracked.state,
                "submission_evidence": evidence,
                "trace_path": stopped.trace_path,
                "updated_at": utc_now(),
            }
        )
        return self._runs.save(completed)

    def get(self, run_id: str) -> PortalRunSnapshot:
        run = self._runs.get(run_id)
        if run is None:
            raise LookupError(f"Portal run {run_id} was not found")
        return run

    def list_runs(self) -> list[PortalRunSnapshot]:
        return self._runs.list_runs()

    def _select_document(
        self, profile_id: str, query: str, preferred_id: str | None
    ) -> CandidateDocumentVersionRecord:
        documents = [
            value
            for value in self._knowledge.list_documents(profile_id)
            if value.kind is DocumentKind.RESUME and not value.archived
        ]
        if not documents:
            raise PortalExecutionError(
                "An approved resume is required before starting a portal run"
            )
        candidates = []
        for document in documents:
            versions = self._knowledge.list_versions(document.id)
            if versions:
                record = self._knowledge.get_version_record(versions[-1].id)
                if record is not None:
                    candidates.append((document, record))
        if preferred_id is not None:
            for _, record in candidates:
                if record.id == preferred_id:
                    return record
            raise PortalExecutionError("Preferred document version is not an active profile resume")
        query_terms = _terms(query)
        candidates.sort(
            key=lambda item: (
                item[0].is_primary,
                bool(query_terms & set(item[0].job_family_tags)),
                item[1].version,
            ),
            reverse=True,
        )
        return candidates[0][1]

    def _qualify(
        self, profile_id: str, requirements: list[str], threshold: float
    ) -> PortalQualification:
        claims = [
            claim
            for claim in self._knowledge.list_claims(profile_id)
            if claim.verification_status is ClaimVerificationStatus.VERIFIED
            and claim.permitted_use in {ClaimPermittedUse.APPLICATIONS, ClaimPermittedUse.ANY}
        ]
        corpus = _terms(" ".join([claim.canonical_key + " " + claim.statement for claim in claims]))
        matched: list[str] = []
        missing: list[str] = []
        for requirement in requirements:
            required_terms = _terms(requirement)
            (matched if required_terms and required_terms <= corpus else missing).append(
                requirement
            )
        score = len(matched) / len(requirements) if requirements else 1.0
        return PortalQualification(
            score=score,
            threshold=threshold,
            eligible=score >= threshold,
            matched_terms=matched,
            missing_terms=missing,
            evidence_claim_ids=[claim.id for claim in claims],
        )

    def _experience_years(self, profile_id: str) -> str:
        for claim in self._knowledge.list_claims(profile_id):
            if claim.verification_status is not ClaimVerificationStatus.VERIFIED:
                continue
            for key in ("years", "years_experience"):
                value = claim.value.get(key)
                if isinstance(value, (int, float)) and value >= 0:
                    return str(int(value))
            months = claim.value.get("months")
            if isinstance(months, (int, float)) and months >= 0:
                return str(max(0, int(months // 12)))
        return "0"

    def _answer(self, profile_id: str, employer: str, title: str) -> str:
        for answer in self._knowledge.list_answers(profile_id):
            if answer.approved and answer.reuse_permission in {
                ClaimPermittedUse.APPLICATIONS,
                ClaimPermittedUse.ANY,
            }:
                return self._cipher.decrypt_bytes(
                    answer.encrypted_answer,
                    context=f"answer:{answer.id}:value",
                ).decode()
        return f"I am interested in the {title} role at {employer}."

    def _transition(
        self,
        workflow_id: str,
        target: WorkflowState,
        cause: str,
        *,
        verification: VerificationResult = VerificationResult.NOT_REQUIRED,
    ) -> WorkflowRunSnapshot:
        current = self._workbench.get_snapshot(workflow_id)
        if current is None:
            raise LookupError(f"Workflow {workflow_id} was not found")
        return self._workbench.apply_transition(
            workflow_id,
            TransitionCommand(
                current_state=current.state,
                next_state=target,
                actor="reference-ats",
                cause=cause,
                verification=verification,
            ),
        )

    def _require_verified(self, session_id: str, action: BrowserAction) -> BrowserActionResult:
        result = self._browser.execute_action(session_id, action)
        if not result.verified:
            raise PortalExecutionError(
                result.error or f"Browser action {action.kind} was not verified"
            )
        return result
