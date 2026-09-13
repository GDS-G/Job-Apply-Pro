"""Local, operator-reviewed evidence; never employer verification or hiring probability."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from job_apply_pro.domain.job_discovery import GreenhouseJobReview
from job_apply_pro.domain.knowledge import CandidateClaim, DocumentSelectionPreview
from job_apply_pro.domain.workflow import WorkflowState

READINESS_POLICY = "reviewed-job-readiness/1"
SELECTION_POLICY = "reviewed-resume-selection/1"
REQUIREMENTS_CONFIRMATION = "APPROVE REVIEWED REQUIREMENTS"
QUALIFICATION_CONFIRMATION = "APPROVE REVIEWED QUALIFICATION"

RequirementClassification = Literal["MANDATORY", "PREFERRED", "AMBIGUOUS"]
FindingStatus = Literal["SUPPORTED", "CONTRADICTED", "UNKNOWN"]
ReviewKind = Literal["REQUIREMENTS", "QUALIFICATION", "SELECTION"]


class JobReadinessError(ValueError):
    """Safe actionable conflict; caller input is never included in the message."""


class ReviewModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceSpan(ReviewModel):
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    text: str = Field(min_length=1, max_length=50_000)


class RequirementChoice(ReviewModel):
    span_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    classification: RequirementClassification


class RequirementsRequest(ReviewModel):
    application_id: str = Field(min_length=1, max_length=100)
    source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    items: list[RequirementChoice] = Field(max_length=100)


class ReviewedRequirement(ReviewModel):
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    span_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    text: str = Field(min_length=1, max_length=50_000)
    classification: RequirementClassification


class RequirementsPreview(ReviewModel):
    application_id: str
    job_id: str
    source_fingerprint: str
    requirements: list[ReviewedRequirement]
    requirements_fingerprint: str
    review_fingerprint: str
    notice: str


class RequirementsApproval(RequirementsRequest):
    review_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class RequirementsReview(RequirementsPreview):
    id: str
    revision: int = Field(ge=1)
    created_at: datetime


class RequirementFinding(ReviewModel):
    requirement_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: FindingStatus
    claim_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(max_length=30)


class QualificationRequest(ReviewModel):
    application_id: str = Field(min_length=1, max_length=100)
    requirements_review_id: str = Field(min_length=1, max_length=100)
    findings: list[RequirementFinding] = Field(max_length=100)


class ReviewedFinding(RequirementFinding):
    text: str
    classification: RequirementClassification


class QualificationPreview(ReviewModel):
    application_id: str
    requirements_review_id: str
    requirements_fingerprint: str
    candidate_fingerprint: str
    policy_version: str
    findings: list[ReviewedFinding]
    mandatory_supported: int
    mandatory_count: int
    preferred_supported: int
    preferred_count: int
    coverage_score: float | None = Field(ge=0, le=1)
    evaluable: bool
    eligible: bool
    review_fingerprint: str
    notice: str


class QualificationApproval(QualificationRequest):
    review_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    approve_eligibility: bool = Field(strict=True)
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class QualificationReview(QualificationPreview):
    id: str
    revision: int = Field(ge=1)
    created_at: datetime
    eligibility_approved: bool


class ReadinessSelectionPreview(ReviewModel):
    selection: DocumentSelectionPreview
    requirements_review_id: str
    qualification_review_id: str
    review_fingerprint: str
    notice: str


class ReadinessSelectionReview(ReviewModel):
    id: str
    revision: int = Field(ge=1)
    created_at: datetime
    application_id: str
    requirements_review_id: str
    qualification_review_id: str
    requirements_fingerprint: str
    candidate_fingerprint: str
    document_fingerprint: str
    document_version_id: str
    review_fingerprint: str
    policy_version: str


class JobReadinessSnapshot(ReviewModel):
    application_id: str
    job_id: str
    profile_id: str
    workflow_id: str
    state: WorkflowState
    supported: bool
    status: Literal[
        "UNSUPPORTED",
        "REQUIREMENTS_REVIEW",
        "QUALIFICATION_REVIEW",
        "ELIGIBILITY_REVIEW",
        "RESUME_REVIEW",
        "READY",
        "STALE",
    ]
    source: GreenhouseJobReview | None
    source_fingerprint: str | None
    spans: list[SourceSpan]
    evidence_claims: list[CandidateClaim]
    requirements_review: RequirementsReview | None
    qualification_review: QualificationReview | None
    selection_review: ReadinessSelectionReview | None
    allowed_actions: list[Literal["REVIEW_REQUIREMENTS", "REVIEW_QUALIFICATION", "SELECT_RESUME"]]
    notice: str
