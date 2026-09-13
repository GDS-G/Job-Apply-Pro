"""Source-exact, human-reviewed local readiness. No network or model calls."""

import hashlib
import json
from uuid import uuid4

from job_apply_pro.domain.applications import Application
from job_apply_pro.domain.job_discovery import SOURCE, GreenhouseJobReview
from job_apply_pro.domain.job_readiness import (
    QUALIFICATION_CONFIRMATION,
    READINESS_POLICY,
    REQUIREMENTS_CONFIRMATION,
    SELECTION_POLICY,
    JobReadinessError,
    JobReadinessSnapshot,
    QualificationApproval,
    QualificationPreview,
    QualificationRequest,
    QualificationReview,
    ReadinessSelectionPreview,
    ReadinessSelectionReview,
    RequirementsApproval,
    RequirementsPreview,
    RequirementsRequest,
    RequirementsReview,
    ReviewedFinding,
    ReviewedRequirement,
    SourceSpan,
)
from job_apply_pro.domain.jobs import Job, JobRequirement
from job_apply_pro.domain.knowledge import (
    CandidateClaim,
    ClaimPermittedUse,
    ClaimVerificationStatus,
    DocumentKind,
    DocumentSelectionApproval,
    DocumentSelectionAudit,
    DocumentSelectionRequest,
)
from job_apply_pro.domain.workflow import WorkflowState, utc_now
from job_apply_pro.security.encryption import DecryptionError
from job_apply_pro.services.knowledge import CandidateKnowledgeError, CandidateKnowledgeService
from job_apply_pro.storage.job_readiness_repository import EARLY_STATES, JobReadinessRepository
from job_apply_pro.storage.repository_contracts import CandidateKnowledgeRepositoryProtocol


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


class JobReadinessService:
    def __init__(
        self,
        repository: JobReadinessRepository,
        knowledge: CandidateKnowledgeRepositoryProtocol,
        documents: CandidateKnowledgeService,
    ) -> None:
        self._repository = repository
        self._knowledge = knowledge
        self._documents = documents

    def _source(
        self, application_id: str
    ) -> tuple[Application, Job, GreenhouseJobReview, str, list[SourceSpan]]:
        application, job = self._repository.application_job(application_id)
        source = self._repository.source(job.id) if job.source == SOURCE else None
        if source is None or application.state not in EARLY_STATES:
            raise JobReadinessError(
                "Only saved public Greenhouse jobs before portal execution "
                "support this local review"
            )
        if (
            job.external_id != f"{source.board_token}:{source.posting_id}"
            or job.title != source.title
            or job.employer != source.employer
            or job.location != source.location
            or job.source_url != source.source_url
            or job.description_hash != hashlib.sha256(source.description.encode()).hexdigest()
        ):
            raise JobReadinessError("Saved job and source disagree; local readiness is blocked")
        source_hash = fingerprint(
            {"job": job.model_dump(mode="json"), "source": source.model_dump(mode="json")}
        )
        # Server-issued exact full lines, not inferred requirements. Line IDs also
        # distinguish repeated identical text. No renderer-supplied offsets/text.
        lines = [
            (index, line)
            for index, line in enumerate(source.description.splitlines())
            if line.strip()
        ]
        if not lines or len(lines) > 500:
            raise JobReadinessError(
                "Saved source exceeds the supported 500-span review; no text was truncated"
            )
        spans = [
            SourceSpan(
                id=fingerprint({"source": source_hash, "line": index, "text": line}), text=line
            )
            for index, line in lines
        ]
        return application, job, source, source_hash, spans

    def _claims(self, profile_id: str) -> tuple[list[CandidateClaim], str]:
        all_claims = self._knowledge.list_claims(profile_id)
        if len(all_claims) > 1000:
            raise JobReadinessError(
                "Candidate evidence exceeds the supported 1000-claim local review"
            )
        eligible: list[CandidateClaim] = []
        sources: dict[str, object] = {}
        verified_versions: dict[str, dict[str, str] | None] = {}
        for claim in sorted(all_claims, key=lambda item: item.id):
            if (
                claim.profile_id != profile_id
                or claim.verification_status is not ClaimVerificationStatus.VERIFIED
                or not claim.locked
                or claim.superseded_by_id is not None
                or claim.permitted_use
                not in {ClaimPermittedUse.APPLICATIONS, ClaimPermittedUse.ANY}
            ):
                continue
            source = self._repository.claim_source(claim)
            if source is None:
                continue
            evidence_version = source.get("document_version_id")
            if isinstance(evidence_version, str):
                if evidence_version not in verified_versions:
                    try:
                        actual = hashlib.sha256(
                            self._documents.get_document_content(evidence_version)
                        ).hexdigest()
                        extraction = self._documents.get_extraction(evidence_version)
                        verified_versions[evidence_version] = {
                            "actual_sha256": actual,
                            "extraction_fingerprint": fingerprint(
                                extraction.model_dump(mode="json")
                            ),
                        }
                    except (
                        OSError,
                        UnicodeError,
                        DecryptionError,
                        CandidateKnowledgeError,
                        LookupError,
                    ):
                        verified_versions[evidence_version] = None
                verified = verified_versions[evidence_version]
                if verified is None or verified["actual_sha256"] != source["content_hash"]:
                    continue
                source["verified_version"] = verified
            eligible.append(claim)
            sources[claim.id] = source
        return eligible, fingerprint(
            {
                "profile": profile_id,
                "claims": [claim.model_dump(mode="json") for claim in eligible],
                "sources": sources,
            }
        )

    def _requirements(self, application_id: str) -> RequirementsReview | None:
        review = self._repository.latest(application_id, "REQUIREMENTS")
        return review if isinstance(review, RequirementsReview) else None

    def _qualification(self, application_id: str) -> QualificationReview | None:
        review = self._repository.latest(application_id, "QUALIFICATION")
        return review if isinstance(review, QualificationReview) else None

    def _selection(self, application_id: str) -> ReadinessSelectionReview | None:
        review = self._repository.latest(application_id, "SELECTION")
        return review if isinstance(review, ReadinessSelectionReview) else None

    def _requirements_hash(self, source_hash: str, requirements: list[ReviewedRequirement]) -> str:
        return fingerprint(
            {
                "policy": READINESS_POLICY,
                "source": source_hash,
                "requirements": [item.model_dump(mode="json") for item in requirements],
            }
        )

    def _valid_requirements(
        self, review: RequirementsReview | None, source_hash: str, spans: list[SourceSpan]
    ) -> bool:
        if review is None or review.source_fingerprint != source_hash:
            return False
        mapping = {span.id: span.text for span in spans}
        return (
            len({item.id for item in review.requirements}) == len(review.requirements)
            and all(
                item.id == item.span_id and mapping.get(item.span_id) == item.text
                for item in review.requirements
            )
            and review.requirements_fingerprint
            == self._requirements_hash(source_hash, review.requirements)
        )

    @staticmethod
    def _valid_qualification(
        review: QualificationReview | None, requirements: RequirementsReview, candidate_hash: str
    ) -> bool:
        return bool(
            review
            and review.requirements_review_id == requirements.id
            and review.requirements_fingerprint == requirements.requirements_fingerprint
            and review.candidate_fingerprint == candidate_hash
            and review.policy_version == READINESS_POLICY
        )

    def snapshot(self, application_id: str) -> JobReadinessSnapshot:
        application, job = self._repository.application_job(application_id)
        base = {
            "application_id": application.id,
            "job_id": job.id,
            "profile_id": application.profile_id,
            "workflow_id": application.workflow_id,
            "state": application.state,
        }
        if (
            job.source != SOURCE
            or application.state not in EARLY_STATES
            or self._repository.source(job.id) is None
        ):
            return JobReadinessSnapshot(
                **base,
                supported=False,
                status="UNSUPPORTED",
                source=None,
                source_fingerprint=None,
                spans=[],
                evidence_claims=[],
                requirements_review=None,
                qualification_review=None,
                selection_review=None,
                allowed_actions=[],
                notice="This local review supports saved public Greenhouse jobs "
                "before portal execution only.",
            )
        _, _, source, source_hash, spans = self._source(application_id)
        claims, candidate_hash = self._claims(application.profile_id)
        requirements, qualification, selection = (
            self._requirements(application_id),
            self._qualification(application_id),
            self._selection(application_id),
        )
        status: str = "REQUIREMENTS_REVIEW"
        actions: list[str] = ["REVIEW_REQUIREMENTS"]
        valid_requirements = self._valid_requirements(requirements, source_hash, spans)
        if requirements is not None:
            status = "QUALIFICATION_REVIEW" if valid_requirements else "STALE"
        if valid_requirements and requirements is not None:
            actions.append("REVIEW_QUALIFICATION")
            if qualification is not None:
                if not self._valid_qualification(qualification, requirements, candidate_hash):
                    status = "STALE"
                elif qualification.eligible and qualification.eligibility_approved:
                    status = "RESUME_REVIEW"
                    actions.append("SELECT_RESUME")
                    if selection is not None:
                        valid_selection = (
                            selection.requirements_review_id == requirements.id
                            and selection.qualification_review_id == qualification.id
                            and selection.requirements_fingerprint
                            == requirements.requirements_fingerprint
                            and selection.candidate_fingerprint == candidate_hash
                            and selection.policy_version == SELECTION_POLICY
                            and selection.document_version_id
                            == application.selected_document_version_id
                            and selection.document_fingerprint
                            == self._document_fingerprint(application.profile_id)
                        )
                        status = "READY" if valid_selection else "STALE"
                elif qualification.eligible:
                    status = "ELIGIBILITY_REVIEW"
        return JobReadinessSnapshot.model_validate(
            base
            | {
                "supported": True,
                "status": status,
                "source": source,
                "source_fingerprint": source_hash,
                "spans": spans,
                "evidence_claims": claims,
                "requirements_review": requirements,
                "qualification_review": qualification,
                "selection_review": selection,
                "allowed_actions": actions,
                "notice": "Local operator-reviewed evidence only. Coverage is not hiring "
                "probability or employer verification. No application has been opened "
                "or submitted by this review.",
            }
        )

    def preview_requirements(self, command: RequirementsRequest) -> RequirementsPreview:
        application, job, _, source_hash, spans = self._source(command.application_id)
        if command.source_fingerprint != source_hash:
            raise JobReadinessError("Saved source changed; reload and review its exact spans")
        if len({item.span_id for item in command.items}) != len(command.items):
            raise JobReadinessError("Select each source span at most once")
        choices = {item.span_id: item.classification for item in command.items}
        if not choices.keys() <= {span.id for span in spans}:
            raise JobReadinessError("Requirement span is not in this saved source")
        requirements = [
            ReviewedRequirement(
                id=span.id, span_id=span.id, text=span.text, classification=choices[span.id]
            )
            for span in spans
            if span.id in choices
        ]
        requirements_hash = self._requirements_hash(source_hash, requirements)
        prior = self._requirements(application.id)
        return RequirementsPreview(
            application_id=application.id,
            job_id=job.id,
            source_fingerprint=source_hash,
            requirements=requirements,
            requirements_fingerprint=requirements_hash,
            review_fingerprint=fingerprint(
                {
                    "application": application.id,
                    "requirements": requirements_hash,
                    "prior": prior.id if prior else None,
                }
            ),
            notice="Review exact employer text and mandatory/preferred wording. "
            "Selecting text does not certify completeness. Empty or ambiguous criteria "
            "cannot clear eligibility.",
        )

    def approve_requirements(self, command: RequirementsApproval) -> JobReadinessSnapshot:
        if command.confirmation_phrase != REQUIREMENTS_CONFIRMATION:
            raise JobReadinessError("Requirements confirmation is required")
        with self._repository.write(command.application_id):
            existing = self._repository.existing(
                command.application_id, "REQUIREMENTS", command.review_fingerprint
            )
            request = RequirementsRequest.model_validate(
                command.model_dump(exclude={"review_fingerprint", "confirmation_phrase"})
            )
            preview = self.preview_requirements(request)
            if isinstance(existing, RequirementsReview):
                latest = self._requirements(command.application_id)
                if (
                    latest is None
                    or latest.id != existing.id
                    or preview.requirements_fingerprint != existing.requirements_fingerprint
                ):
                    raise JobReadinessError(
                        "Requirement approval is superseded or stale; review again"
                    )
            else:
                if preview.review_fingerprint != command.review_fingerprint:
                    raise JobReadinessError("Requirements preview changed; review again")
                identity, revision, now = self._repository.metadata(
                    command.application_id, "REQUIREMENTS"
                )
                self._repository.append(
                    "REQUIREMENTS",
                    command.review_fingerprint,
                    RequirementsReview(
                        **preview.model_dump(), id=identity, revision=revision, created_at=now
                    ),
                )
        return self.snapshot(command.application_id)

    def preview_qualification(self, command: QualificationRequest) -> QualificationPreview:
        application, _, _, source_hash, spans = self._source(command.application_id)
        requirements = self._requirements(application.id)
        if (
            requirements is None
            or requirements.id != command.requirements_review_id
            or not self._valid_requirements(requirements, source_hash, spans)
        ):
            raise JobReadinessError(
                "Approve the current exact requirements before reviewing qualification"
            )
        claims, candidate_hash = self._claims(application.profile_id)
        allowed_claims = {claim.id for claim in claims}
        if len({item.requirement_id for item in command.findings}) != len(command.findings):
            raise JobReadinessError("Review each requirement exactly once")
        mapping = {item.requirement_id: item for item in command.findings}
        if mapping.keys() != {item.id for item in requirements.requirements}:
            raise JobReadinessError(
                "Review every current requirement, and no unrelated requirement"
            )
        findings: list[ReviewedFinding] = []
        for item in requirements.requirements:
            finding = mapping[item.id]
            if (
                len(set(finding.claim_ids)) != len(finding.claim_ids)
                or not set(finding.claim_ids) <= allowed_claims
            ):
                raise JobReadinessError(
                    "Evidence must reference distinct current locked application-approved "
                    "claims from this profile"
                )
            if (finding.status == "UNKNOWN" and finding.claim_ids) or (
                finding.status != "UNKNOWN" and not finding.claim_ids
            ):
                raise JobReadinessError(
                    "Supported or contradicted findings require reviewed claim links; "
                    "unknown findings have no asserted evidence"
                )
            findings.append(
                ReviewedFinding(
                    **finding.model_dump(exclude={"claim_ids"}),
                    claim_ids=sorted(finding.claim_ids),
                    text=item.text,
                    classification=item.classification,
                )
            )
        mandatory = [item for item in findings if item.classification == "MANDATORY"]
        preferred = [item for item in findings if item.classification == "PREFERRED"]
        evaluable = bool(mandatory) and not any(
            item.classification == "AMBIGUOUS" for item in findings
        )
        mandatory_supported = sum(item.status == "SUPPORTED" for item in mandatory)
        preferred_supported = sum(item.status == "SUPPORTED" for item in preferred)
        eligible = evaluable and mandatory_supported == len(mandatory)
        prior = self._qualification(application.id)
        payload = {
            "application_id": application.id,
            "requirements_review_id": requirements.id,
            "requirements_fingerprint": requirements.requirements_fingerprint,
            "candidate_fingerprint": candidate_hash,
            "policy_version": READINESS_POLICY,
            "findings": [item.model_dump(mode="json") for item in findings],
            "mandatory_supported": mandatory_supported,
            "mandatory_count": len(mandatory),
            "preferred_supported": preferred_supported,
            "preferred_count": len(preferred),
            "coverage_score": (mandatory_supported + preferred_supported) / len(findings)
            if evaluable
            else None,
            "evaluable": evaluable,
            "eligible": eligible,
            "notice": "Coverage counts your reviewed evidence links, not semantic inference, "
            "employer verification, or hiring probability. Eligibility clearance requires "
            "at least one explicit mandatory criterion, no ambiguous criteria, and support "
            "for every mandatory criterion.",
        }
        return QualificationPreview.model_validate(
            payload
            | {"review_fingerprint": fingerprint(payload | {"prior": prior.id if prior else None})}
        )

    def approve_qualification(self, command: QualificationApproval) -> JobReadinessSnapshot:
        if command.confirmation_phrase != QUALIFICATION_CONFIRMATION:
            raise JobReadinessError("Qualification confirmation is required")
        request_hash = fingerprint(command.model_dump(mode="json", exclude={"confirmation_phrase"}))
        with self._repository.write(command.application_id):
            preview = self.preview_qualification(
                QualificationRequest.model_validate(
                    command.model_dump(
                        exclude={"review_fingerprint", "approve_eligibility", "confirmation_phrase"}
                    )
                )
            )
            existing = self._repository.existing(
                command.application_id, "QUALIFICATION", request_hash
            )
            if isinstance(existing, QualificationReview):
                latest = self._qualification(command.application_id)
                if (
                    latest is None
                    or latest.id != existing.id
                    or preview.candidate_fingerprint != existing.candidate_fingerprint
                    or preview.requirements_fingerprint != existing.requirements_fingerprint
                ):
                    raise JobReadinessError(
                        "Qualification approval is superseded or stale; review again"
                    )
            else:
                if preview.review_fingerprint != command.review_fingerprint:
                    raise JobReadinessError("Qualification evidence changed; review again")
                if command.approve_eligibility and not preview.eligible:
                    raise JobReadinessError(
                        "Missing, unknown, ambiguous, or absent mandatory evidence "
                        "prevents eligibility clearance"
                    )
                identity, revision, now = self._repository.metadata(
                    command.application_id, "QUALIFICATION"
                )
                self._repository.append(
                    "QUALIFICATION",
                    request_hash,
                    QualificationReview(
                        **preview.model_dump(),
                        id=identity,
                        revision=revision,
                        created_at=now,
                        eligibility_approved=command.approve_eligibility,
                    ),
                )
                if preview.evaluable:
                    self._repository.advance(
                        command.application_id,
                        WorkflowState.ELIGIBILITY_CHECKED
                        if command.approve_eligibility
                        else WorkflowState.SCORED,
                        identity,
                    )
        return self.snapshot(command.application_id)

    def _require_qualification(
        self, application_id: str
    ) -> tuple[Application, RequirementsReview, QualificationReview]:
        application, _, _, source_hash, spans = self._source(application_id)
        requirements, qualification = (
            self._requirements(application_id),
            self._qualification(application_id),
        )
        _, candidate_hash = self._claims(application.profile_id)
        if (
            requirements is None
            or not self._valid_requirements(requirements, source_hash, spans)
            or qualification is None
            or not self._valid_qualification(qualification, requirements, candidate_hash)
            or not qualification.evaluable
            or not qualification.eligible
            or not qualification.eligibility_approved
        ):
            raise JobReadinessError(
                "Review current requirements, candidate evidence, and eligibility "
                "before selecting a resume"
            )
        return application, requirements, qualification

    def _document_fingerprint(self, profile_id: str) -> str:
        documents = self._knowledge.list_documents(profile_id)
        if len(documents) > 100:
            raise JobReadinessError("Resume review exceeds the supported 100-document inventory")
        payload: list[dict[str, object]] = []
        for document in sorted(documents, key=lambda item: item.id):
            if document.kind is not DocumentKind.RESUME or document.archived:
                continue
            versions = self._knowledge.list_versions(document.id)
            if not versions:
                continue
            version = max(versions, key=lambda item: (item.version, item.created_at, item.id))
            content = self._documents.get_document_content(version.id)
            actual_hash = hashlib.sha256(content).hexdigest()
            if actual_hash != version.sha256:
                raise JobReadinessError("Immutable resume bytes changed; selection is blocked")
            extraction = self._documents.get_extraction(version.id)
            payload.append(
                {
                    "document": document.model_dump(mode="json"),
                    "version": version.model_dump(mode="json"),
                    "actual_sha256": actual_hash,
                    "extraction": fingerprint(extraction.model_dump(mode="json")),
                }
            )
        return fingerprint(
            {"profile": profile_id, "documents": payload, "policy": SELECTION_POLICY}
        )

    def preview_resume(self, command: DocumentSelectionRequest) -> ReadinessSelectionPreview:
        if command.kind is not DocumentKind.RESUME:
            raise JobReadinessError("Readiness selection supports resumes only")
        application, requirements, qualification = self._require_qualification(
            command.application_id
        )
        projected = [
            JobRequirement(
                id=item.id,
                job_id=application.job_id,
                category="operator-reviewed-source",
                text=item.text,
                required=item.classification == "MANDATORY",
                evidence={
                    "source": SOURCE,
                    "source_fingerprint": requirements.source_fingerprint,
                    "requirements_review_id": requirements.id,
                    "span_id": item.span_id,
                },
            )
            for item in requirements.requirements
        ]
        selection = self._documents.preview_document_selection(
            command, _reviewed_requirements=projected
        )
        inventory_hash = self._document_fingerprint(application.profile_id)
        prior = self._selection(application.id)
        strong_hash = fingerprint(
            {
                "selection": selection.model_dump(mode="json"),
                "criteria": command.model_dump(mode="json"),
                "requirements": requirements.model_dump(mode="json"),
                "qualification": qualification.model_dump(mode="json"),
                "inventory": inventory_hash,
                "policy": SELECTION_POLICY,
                "prior": prior.id if prior else None,
            }
        )
        return ReadinessSelectionPreview(
            selection=selection,
            requirements_review_id=requirements.id,
            qualification_review_id=qualification.id,
            review_fingerprint=strong_hash,
            notice="Document scores rank text coverage and preferences only; they do not "
            "prove qualifications. Review the exact immutable version before selection. "
            "No upload or submission occurs.",
        )

    def approve_resume(self, command: DocumentSelectionApproval) -> JobReadinessSnapshot:
        if command.confirmation_phrase != "SELECT REVIEWED DOCUMENT":
            raise JobReadinessError("Resume selection confirmation is required")
        request_hash = fingerprint(command.model_dump(mode="json", exclude={"confirmation_phrase"}))
        with self._repository.write(command.application_id):
            application, requirements, qualification = self._require_qualification(
                command.application_id
            )
            inventory_hash = self._document_fingerprint(application.profile_id)
            existing = self._repository.existing(command.application_id, "SELECTION", request_hash)
            if isinstance(existing, ReadinessSelectionReview):
                latest = self._selection(command.application_id)
                if (
                    latest is None
                    or latest.id != existing.id
                    or existing.document_fingerprint != inventory_hash
                    or existing.qualification_review_id != qualification.id
                    or existing.requirements_review_id != requirements.id
                    or application.selected_document_version_id != existing.document_version_id
                ):
                    raise JobReadinessError("Resume approval is superseded or stale; review again")
            else:
                preview = self.preview_resume(
                    DocumentSelectionRequest.model_validate(
                        command.model_dump(
                            exclude={
                                "document_version_id",
                                "review_fingerprint",
                                "confirmation_phrase",
                            }
                        )
                    )
                )
                if preview.review_fingerprint != command.review_fingerprint:
                    raise JobReadinessError(
                        "Resume, requirements, or qualification changed; review again"
                    )
                selected = next(
                    (
                        item
                        for item in preview.selection.recommendations
                        if item.document_version_id == command.document_version_id
                    ),
                    None,
                )
                if selected is None:
                    raise JobReadinessError(
                        "Select an immutable version from the reviewed recommendation set"
                    )
                identity, revision, now = self._repository.metadata(application.id, "SELECTION")
                record = ReadinessSelectionReview(
                    id=identity,
                    revision=revision,
                    created_at=now,
                    application_id=application.id,
                    requirements_review_id=requirements.id,
                    qualification_review_id=qualification.id,
                    requirements_fingerprint=requirements.requirements_fingerprint,
                    candidate_fingerprint=qualification.candidate_fingerprint,
                    document_fingerprint=inventory_hash,
                    document_version_id=selected.document_version_id,
                    review_fingerprint=command.review_fingerprint,
                    policy_version=SELECTION_POLICY,
                )
                self._repository.append("SELECTION", request_hash, record)
                self._repository.select_document(
                    DocumentSelectionAudit(
                        id=str(uuid4()),
                        application_id=application.id,
                        profile_id=application.profile_id,
                        job_id=application.job_id,
                        document_id=selected.document_id,
                        document_version_id=selected.document_version_id,
                        score=selected.score,
                        review_fingerprint=command.review_fingerprint,
                        criteria={
                            "request": command.model_dump(
                                mode="json", exclude={"confirmation_phrase"}
                            ),
                            "readiness_review_id": identity,
                            "requirements_review_id": requirements.id,
                            "qualification_review_id": qualification.id,
                            "policy_version": SELECTION_POLICY,
                        },
                        reasons=selected.reasons,
                        created_at=utc_now(),
                    )
                )
                self._repository.advance(application.id, WorkflowState.DOCUMENTS_SELECTED, identity)
        return self.snapshot(command.application_id)
