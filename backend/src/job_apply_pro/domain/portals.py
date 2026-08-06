from datetime import datetime
from enum import StrEnum

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from job_apply_pro.domain.workflow import WorkflowState


class PortalKind(StrEnum):
    REFERENCE_ATS = "REFERENCE_ATS"


class PortalCapability(StrEnum):
    SEARCH = "SEARCH"
    JOB_EXTRACTION = "JOB_EXTRACTION"
    APPLICATION_LAUNCH = "APPLICATION_LAUNCH"
    MULTI_PAGE_FORM = "MULTI_PAGE_FORM"
    DOCUMENT_UPLOAD = "DOCUMENT_UPLOAD"
    SUBMISSION = "SUBMISSION"
    CONFIRMATION = "CONFIRMATION"


REFERENCE_ATS_CAPABILITIES = tuple(PortalCapability)


class PortalJobPosting(BaseModel):
    model_config = ConfigDict(frozen=True)

    external_id: str = Field(min_length=1, max_length=200)
    employer: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=1, max_length=50_000)
    requirements: list[str] = Field(default_factory=list, max_length=100)
    source_url: AnyHttpUrl


class PortalFieldMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_type: str = Field(min_length=1, max_length=100)
    canonical_field: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=300)
    required: bool = False


class PortalQualification(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    eligible: bool
    matched_terms: list[str]
    missing_terms: list[str]
    evidence_claim_ids: list[str]


class SubmissionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    confirmation_code: str = Field(min_length=1, max_length=200)
    confirmation_url: str = Field(min_length=1, max_length=2_000)
    page_fingerprint: str = Field(min_length=1, max_length=200)
    visible_signal: str = Field(min_length=1, max_length=1_000)
    verified_at: datetime


class ReferencePortalRunCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str = Field(min_length=1, max_length=100)
    portal_origin: AnyHttpUrl
    query: str = Field(min_length=1, max_length=200)
    minimum_fit_score: float = Field(default=0.5, ge=0, le=1)
    preferred_document_version_id: str | None = None
    headless: bool | None = None


class SubmissionApproval(BaseModel):
    model_config = ConfigDict(frozen=True)

    review_fingerprint: str = Field(min_length=1, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=40)


class PortalRunSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    portal: PortalKind
    capabilities: list[PortalCapability]
    workflow_id: str
    application_id: str
    browser_session_id: str
    profile_id: str
    job_id: str
    state: WorkflowState
    portal_origin: str
    query: str
    deduplicated: bool
    qualification: PortalQualification
    selected_document_version_id: str
    field_mappings: list[PortalFieldMapping]
    review_fingerprint: str
    submission_evidence: SubmissionEvidence | None = None
    trace_path: str | None = None
    created_at: datetime
    updated_at: datetime
