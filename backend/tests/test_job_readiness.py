"""Synthetic saved-source progression; no provider or AI qualification calls."""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_apply_pro.domain.job_discovery import GreenhouseImportRequest
from job_apply_pro.domain.job_readiness import (
    QUALIFICATION_CONFIRMATION,
    REQUIREMENTS_CONFIRMATION,
    JobReadinessError,
    QualificationApproval,
    QualificationRequest,
    RequirementsApproval,
    RequirementsRequest,
)
from job_apply_pro.domain.knowledge import (
    ClaimPermittedUse,
    ClaimReview,
    DocumentKind,
    DocumentSelectionApproval,
    DocumentSelectionRequest,
)
from job_apply_pro.domain.workflow import WorkflowState
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.job_readiness import JobReadinessService
from job_apply_pro.services.knowledge import (
    CandidateKnowledgeConflictError,
    CandidateKnowledgeService,
)
from job_apply_pro.storage.job_readiness_repository import JobReadinessRepository
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.models import (
    ApplicationRow,
    CandidateClaimRow,
    DocumentRow,
    DocumentSelectionAuditRow,
    JobReadinessReviewRow,
    JobRequirementRow,
    WorkflowEventRow,
)
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    JobRepository,
)
from test_greenhouse_discovery_import import profile
from test_greenhouse_discovery_import import service as importer
from test_greenhouse_public_client import BOARD, POSTING_ID, client_for, posting, review


class Fixture:
    def __init__(self, session: Session, root: Path) -> None:
        self.session = session
        self.profile_id = profile(session)
        client = client_for(
            {**posting(), "content": "<p>Python is mandatory.</p><p>Docker is preferred.</p>"}
        )
        source = review(client)
        saved = importer(session, client).import_job(
            GreenhouseImportRequest(
                board_token=BOARD,
                posting_id=POSTING_ID,
                profile_id=self.profile_id,
                review_fingerprint=source.review_fingerprint,
            )
        )
        assert saved.workflow
        self.application_id = saved.workflow.application_id
        self.cipher = SensitiveDataCipher(StaticKeyProvider(b"g" * 32))
        self.knowledge = CandidateKnowledgeRepository(session)
        self.documents = CandidateKnowledgeService(
            self.knowledge,
            CandidateRepository(session),
            JobRepository(session),
            ApplicationRepository(session),
            self.cipher,
            document_data_dir=root / "documents",
            document_max_bytes=1_000_000,
        )
        self.repository = JobReadinessRepository(session, self.cipher)
        self.service = JobReadinessService(self.repository, self.knowledge, self.documents)
        document = self.documents.import_document(
            self.profile_id,
            file_name="resume.txt",
            data=b"Synthetic Candidate\nSkills: Python, Docker\n",
            kind=DocumentKind.RESUME,
            display_name="Resume",
            variant_label="General",
            job_family_tags=["python"],
            is_primary=True,
        )
        self.version_id = document.version.id
        for claim in document.proposed_claims:
            self.documents.review_claim(
                claim.id, ClaimReview(approved=True, permitted_use=ClaimPermittedUse.APPLICATIONS)
            )
        self.claim_ids = [
            claim.id for claim in self.service.snapshot(self.application_id).evidence_claims
        ]
        assert self.claim_ids

    def requirements(self, classifications: list[str] | None = None) -> RequirementsApproval:
        snapshot = self.service.snapshot(self.application_id)
        assert snapshot.source_fingerprint
        choices = classifications if classifications is not None else ["MANDATORY", "PREFERRED"]
        request = RequirementsRequest.model_validate(
            {
                "application_id": self.application_id,
                "source_fingerprint": snapshot.source_fingerprint,
                "items": [
                    {"span_id": span.id, "classification": classification}
                    for span, classification in zip(snapshot.spans, choices, strict=False)
                ],
            }
        )
        preview = self.service.preview_requirements(request)
        approval = RequirementsApproval(
            **request.model_dump(),
            review_fingerprint=preview.review_fingerprint,
            confirmation_phrase=REQUIREMENTS_CONFIRMATION,
        )
        self.service.approve_requirements(approval)
        return approval

    def qualification(
        self, *, status: str = "SUPPORTED", approve: bool = True
    ) -> QualificationApproval:
        snapshot = self.service.snapshot(self.application_id)
        assert snapshot.requirements_review
        request = QualificationRequest.model_validate(
            {
                "application_id": self.application_id,
                "requirements_review_id": snapshot.requirements_review.id,
                "findings": [
                    {
                        "requirement_id": item.id,
                        "status": status,
                        "claim_ids": self.claim_ids if status != "UNKNOWN" else [],
                    }
                    for item in snapshot.requirements_review.requirements
                ],
            }
        )
        preview = self.service.preview_qualification(request)
        return QualificationApproval(
            **request.model_dump(),
            review_fingerprint=preview.review_fingerprint,
            approve_eligibility=approve,
            confirmation_phrase=QUALIFICATION_CONFIRMATION,
        )

    def ready_to_select(self) -> None:
        self.requirements()
        self.service.approve_qualification(self.qualification())

    def selection(self) -> DocumentSelectionApproval:
        request = DocumentSelectionRequest(application_id=self.application_id)
        preview = self.service.preview_resume(request)
        return DocumentSelectionApproval(
            **request.model_dump(),
            document_version_id=self.version_id,
            review_fingerprint=preview.review_fingerprint,
            confirmation_phrase="SELECT REVIEWED DOCUMENT",
        )


@pytest.fixture
def fixture(session: Session, tmp_path: Path) -> Fixture:
    return Fixture(session, tmp_path)


def test_real_progression_is_reviewed_atomic_encrypted_and_replay_safe(fixture: Fixture) -> None:
    initial = fixture.service.snapshot(fixture.application_id)
    assert initial.state is WorkflowState.DEDUPLICATED
    assert initial.status == "REQUIREMENTS_REVIEW"
    assert initial.requirements_review is None and initial.qualification_review is None
    requirement_approval = fixture.requirements()
    after_requirements = fixture.service.approve_requirements(requirement_approval)
    assert after_requirements.state is WorkflowState.DEDUPLICATED
    qualification = fixture.qualification(approve=False)
    scored = fixture.service.approve_qualification(qualification)
    assert scored.state is WorkflowState.SCORED and scored.status == "ELIGIBILITY_REVIEW"
    assert fixture.service.approve_qualification(qualification) == scored
    qualified = fixture.service.approve_qualification(fixture.qualification())
    assert qualified.state is WorkflowState.ELIGIBILITY_CHECKED
    selection = fixture.selection()
    selected = fixture.service.approve_resume(selection)
    assert selected.state is WorkflowState.DOCUMENTS_SELECTED and selected.status == "READY"
    assert fixture.service.approve_resume(selection) == selected
    rows = fixture.session.scalars(select(JobReadinessReviewRow)).all()
    assert len(rows) == 4
    assert all(row.encrypted_payload.startswith("jap:v1:") for row in rows)
    assert all("Python" not in row.encrypted_payload for row in rows)
    assert fixture.session.scalar(select(func.count(JobRequirementRow.id))) == 0
    assert fixture.session.scalar(select(func.count(DocumentSelectionAuditRow.id))) == 1
    events = fixture.session.scalars(
        select(WorkflowEventRow).order_by(WorkflowEventRow.sequence)
    ).all()
    assert [item.next_state for item in events] == [
        "DEDUPLICATED",
        "SCORED",
        "ELIGIBILITY_CHECKED",
        "DOCUMENTS_SELECTED",
    ]
    assert all("no portal action" in item.cause for item in events[1:])


@pytest.mark.parametrize(
    "classifications", [[], ["PREFERRED"], ["AMBIGUOUS"], ["MANDATORY", "AMBIGUOUS"]]
)
def test_empty_or_ambiguous_requirements_never_produce_perfect_qualification(
    fixture: Fixture, classifications: list[str]
) -> None:
    fixture.requirements(classifications)
    approval = fixture.qualification(approve=False)
    reviewed = fixture.service.approve_qualification(approval)
    assert reviewed.qualification_review
    assert reviewed.qualification_review.coverage_score is None
    assert (
        not reviewed.qualification_review.evaluable and not reviewed.qualification_review.eligible
    )
    assert reviewed.state is WorkflowState.DEDUPLICATED
    with pytest.raises(JobReadinessError, match="prevents eligibility"):
        fixture.service.approve_qualification(fixture.qualification(approve=True))


@pytest.mark.parametrize("status", ["UNKNOWN", "CONTRADICTED"])
def test_unknown_or_contradicted_mandatory_evidence_blocks_clearance(
    fixture: Fixture, status: str
) -> None:
    fixture.requirements()
    review_command = fixture.qualification(status=status, approve=False)
    result = fixture.service.approve_qualification(review_command)
    assert result.qualification_review and result.qualification_review.coverage_score == 0
    assert result.state is WorkflowState.SCORED
    with pytest.raises(JobReadinessError, match="prevents eligibility"):
        fixture.service.approve_qualification(fixture.qualification(status=status))


def test_public_job_cannot_bypass_readiness_via_generic_resume_selection(fixture: Fixture) -> None:
    with pytest.raises(CandidateKnowledgeConflictError, match="Reviewed Job Readiness"):
        fixture.documents.preview_document_selection(
            DocumentSelectionRequest(application_id=fixture.application_id)
        )
    with pytest.raises(JobReadinessError, match="eligibility"):
        fixture.service.preview_resume(
            DocumentSelectionRequest(application_id=fixture.application_id)
        )


@pytest.mark.parametrize(
    "mutation", ["statement", "locked", "permission", "verification", "superseded"]
)
def test_changed_candidate_evidence_invalidates_qualification_approval(
    fixture: Fixture, mutation: str
) -> None:
    fixture.requirements()
    approval = fixture.qualification()
    row = fixture.session.get(CandidateClaimRow, fixture.claim_ids[0])
    assert row
    if mutation == "statement":
        row.statement += " Changed source statement."
    elif mutation == "locked":
        row.locked = False
    elif mutation == "permission":
        row.permitted_use = "PROFILE_ONLY"
    elif mutation == "verification":
        row.verification_status = "REJECTED"
    else:
        row.superseded_by_id = fixture.claim_ids[-1]
    fixture.session.commit()
    with pytest.raises(JobReadinessError):
        fixture.service.approve_qualification(approval)
    assert fixture.service.snapshot(fixture.application_id).state is WorkflowState.DEDUPLICATED


def test_same_score_requirement_change_invalidates_resume_review(fixture: Fixture) -> None:
    fixture.ready_to_select()
    stale = fixture.selection()
    fixture.requirements(["MANDATORY", "MANDATORY"])
    assert fixture.service.snapshot(fixture.application_id).status == "STALE"
    fixture.service.approve_qualification(fixture.qualification())
    fresh = fixture.selection()
    assert stale.review_fingerprint != fresh.review_fingerprint
    with pytest.raises(JobReadinessError, match="changed"):
        fixture.service.approve_resume(stale)


def test_document_metadata_change_marks_current_selection_stale_without_rewriting_history(
    fixture: Fixture,
) -> None:
    fixture.ready_to_select()
    fixture.service.approve_resume(fixture.selection())
    event_count = fixture.session.scalar(select(func.count(WorkflowEventRow.id)))
    row = fixture.session.scalar(select(DocumentRow))
    assert row
    row.variant_label = "Changed variant"
    fixture.session.commit()
    current = fixture.service.snapshot(fixture.application_id)
    assert current.status == "STALE" and current.state is WorkflowState.DOCUMENTS_SELECTED
    assert fixture.session.scalar(select(func.count(WorkflowEventRow.id))) == event_count


@pytest.mark.parametrize("operation", ["requirements", "qualification", "selection"])
def test_incorrect_confirmation_writes_nothing(fixture: Fixture, operation: str) -> None:
    if operation == "requirements":
        command = fixture.requirements().model_copy(update={"confirmation_phrase": "NO"})

        def action() -> object:
            return fixture.service.approve_requirements(command)
    elif operation == "qualification":
        fixture.requirements()
        qualification = fixture.qualification().model_copy(update={"confirmation_phrase": "NO"})

        def action() -> object:
            return fixture.service.approve_qualification(qualification)
    else:
        fixture.ready_to_select()
        selection = fixture.selection().model_copy(update={"confirmation_phrase": "NO"})

        def action() -> object:
            return fixture.service.approve_resume(selection)

    before = fixture.session.scalar(select(func.count(JobReadinessReviewRow.id)))
    with pytest.raises(JobReadinessError, match="confirmation"):
        action()
    assert fixture.session.scalar(select(func.count(JobReadinessReviewRow.id))) == before


def test_selection_failure_rolls_back_audit_version_and_transition(
    fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture.ready_to_select()
    selection = fixture.selection()
    before = fixture.session.scalar(select(func.count(JobReadinessReviewRow.id)))

    def fail(*_args: object) -> None:
        raise RuntimeError("synthetic transaction failure")

    monkeypatch.setattr(fixture.repository, "advance", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        fixture.service.approve_resume(selection)
    application = fixture.session.get(ApplicationRow, fixture.application_id)
    assert application and application.selected_document_version_id is None
    assert application.state == "ELIGIBILITY_CHECKED"
    assert fixture.session.scalar(select(func.count(JobReadinessReviewRow.id))) == before
    assert fixture.session.scalar(select(func.count(DocumentSelectionAuditRow.id))) == 0


@pytest.mark.parametrize("mutation", ["duplicate", "foreign", "source"])
def test_requirements_use_only_unique_current_server_spans(fixture: Fixture, mutation: str) -> None:
    snapshot = fixture.service.snapshot(fixture.application_id)
    assert snapshot.source_fingerprint
    item = {"span_id": snapshot.spans[0].id, "classification": "MANDATORY"}
    request = RequirementsRequest.model_validate(
        {
            "application_id": fixture.application_id,
            "source_fingerprint": "a" * 64 if mutation == "source" else snapshot.source_fingerprint,
            "items": [item, item]
            if mutation == "duplicate"
            else [item | {"span_id": "a" * 64}]
            if mutation == "foreign"
            else [item],
        }
    )
    with pytest.raises(JobReadinessError):
        fixture.service.preview_requirements(request)
    assert fixture.service.snapshot(fixture.application_id).requirements_review is None


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "foreign_requirement",
        "duplicate_requirement",
        "foreign_claim",
        "duplicate_claim",
        "empty_support",
        "asserted_unknown",
    ],
)
def test_qualification_rejects_incomplete_or_unrelated_evidence(
    fixture: Fixture, mutation: str
) -> None:
    fixture.requirements()
    command = fixture.qualification()
    data = command.model_dump(
        exclude={"review_fingerprint", "approve_eligibility", "confirmation_phrase"}
    )
    findings = data["findings"]
    if mutation == "missing":
        findings.pop()
    elif mutation == "foreign_requirement":
        findings[0]["requirement_id"] = "a" * 64
    elif mutation == "duplicate_requirement":
        findings.append(findings[0])
    elif mutation == "foreign_claim":
        findings[0]["claim_ids"] = ["other-profile-claim"]
    elif mutation == "duplicate_claim":
        findings[0]["claim_ids"] = [fixture.claim_ids[0], fixture.claim_ids[0]]
    elif mutation == "empty_support":
        findings[0]["claim_ids"] = []
    else:
        findings[0]["status"] = "UNKNOWN"
    with pytest.raises(JobReadinessError):
        fixture.service.preview_qualification(QualificationRequest.model_validate(data))


def test_keyword_overlap_never_automatically_produces_supported_findings(fixture: Fixture) -> None:
    fixture.requirements()
    command = fixture.qualification(status="UNKNOWN", approve=False)
    result = fixture.service.approve_qualification(command)
    assert result.qualification_review
    assert all(item.status == "UNKNOWN" for item in result.qualification_review.findings)
    assert not result.qualification_review.eligible


def test_reviewed_source_and_claim_versions_are_bound_even_with_same_scores(
    fixture: Fixture,
) -> None:
    fixture.ready_to_select()
    stale = fixture.selection()
    from job_apply_pro.storage.models import EvidenceSourceRow

    claim = fixture.knowledge.get_claim(fixture.claim_ids[0])
    assert claim and claim.evidence_source_id
    evidence = fixture.session.get(EvidenceSourceRow, claim.evidence_source_id)
    assert evidence
    evidence.source_label = "Revised source metadata"
    fixture.session.commit()
    assert fixture.service.snapshot(fixture.application_id).status == "STALE"
    with pytest.raises(JobReadinessError):
        fixture.service.approve_resume(stale)


def test_tampered_immutable_resume_bytes_block_selection(fixture: Fixture) -> None:
    fixture.ready_to_select()
    approval = fixture.selection()
    version = fixture.knowledge.get_version_record(fixture.version_id)
    assert version
    Path(version.storage_path).write_text(
        fixture.cipher.encrypt_bytes(
            b"Different bytes with valid encryption", context=f"document:{version.id}:file"
        ),
        encoding="ascii",
    )
    with pytest.raises(JobReadinessError, match="candidate evidence"):
        fixture.service.approve_resume(approval)
    application = fixture.session.get(ApplicationRow, fixture.application_id)
    assert application and application.selected_document_version_id is None


def test_policy_change_invalidates_existing_requirement_review(
    fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import job_apply_pro.services.job_readiness as readiness

    fixture.ready_to_select()
    approval = fixture.selection()
    monkeypatch.setattr(readiness, "READINESS_POLICY", "reviewed-job-readiness/test-next")
    assert fixture.service.snapshot(fixture.application_id).status == "STALE"
    with pytest.raises(JobReadinessError):
        fixture.service.approve_resume(approval)


def test_approvals_after_portal_execution_are_blocked(fixture: Fixture) -> None:
    fixture.ready_to_select()
    approval = fixture.selection()
    application = fixture.session.get(ApplicationRow, fixture.application_id)
    assert application
    application.state = "APPLICATION_OPENED"
    fixture.session.commit()
    assert not fixture.service.snapshot(fixture.application_id).supported
    with pytest.raises(JobReadinessError, match="before portal"):
        fixture.service.approve_resume(approval)


@pytest.mark.parametrize("kind", [DocumentKind.CERTIFICATION, DocumentKind.RESUME])
@pytest.mark.parametrize("damage", ["missing", "corrupt", "non_ascii", "different"])
def test_linked_nonresume_and_older_version_bytes_are_current_evidence(
    fixture: Fixture, kind: DocumentKind, damage: str
) -> None:
    from uuid import uuid4

    from job_apply_pro.storage.models import DocumentVersionRow

    imported = fixture.documents.import_document(
        fixture.profile_id,
        file_name="evidence.txt",
        data=b"Skills: AWS",
        kind=kind,
        display_name="Supporting evidence",
        variant_label="Evidence",
        job_family_tags=[],
        is_primary=False,
    )
    for claim in imported.proposed_claims:
        fixture.documents.review_claim(
            claim.id, ClaimReview(approved=True, permitted_use=ClaimPermittedUse.APPLICATIONS)
        )
        fixture.claim_ids.append(claim.id)
    original = fixture.knowledge.get_version_record(imported.version.id)
    assert original
    if kind is DocumentKind.RESUME:
        identity = str(uuid4())
        path = Path(original.storage_path).with_name(f"{identity}.enc")
        path.write_text(
            fixture.cipher.encrypt_bytes(b"Skills: AWS", context=f"document:{identity}:file"),
            encoding="ascii",
        )
        payload = original.model_dump(
            exclude={"id", "version", "storage_path", "encrypted_extraction"}
        )
        fixture.session.add(
            DocumentVersionRow(
                **payload,
                id=identity,
                version=2,
                storage_path=str(path),
                encrypted_extraction=fixture.cipher.encrypt_json(
                    imported.extraction.model_dump(mode="json"),
                    context=f"document:{identity}:extraction",
                ),
            )
        )
        fixture.session.commit()
    fixture.ready_to_select()
    approval = fixture.selection()
    evidence_path = Path(original.storage_path)
    if damage == "missing":
        evidence_path.unlink()
    elif damage == "corrupt":
        evidence_path.write_text("synthetic invalid ciphertext", encoding="ascii")
    elif damage == "non_ascii":
        evidence_path.write_bytes(b"\xff")
    else:
        evidence_path.write_text(
            fixture.cipher.encrypt_bytes(
                b"Changed reviewed evidence", context=f"document:{original.id}:file"
            ),
            encoding="ascii",
        )
    assert fixture.service.snapshot(fixture.application_id).status == "STALE"
    with pytest.raises(JobReadinessError, match="candidate evidence"):
        fixture.service.approve_resume(approval)
