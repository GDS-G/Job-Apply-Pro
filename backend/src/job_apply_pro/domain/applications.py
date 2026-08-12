from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from job_apply_pro.domain.workflow import WorkflowState


class CanonicalField(StrEnum):
    FULL_NAME = "FULL_NAME"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ADDRESS = "ADDRESS"
    WORK_AUTHORIZATION = "WORK_AUTHORIZATION"
    SPONSORSHIP_REQUIRED = "SPONSORSHIP_REQUIRED"
    SALARY_EXPECTATION = "SALARY_EXPECTATION"
    START_DATE = "START_DATE"
    CUSTOM = "CUSTOM"


class ApplicationDocumentRole(StrEnum):
    RESUME = "RESUME"
    COVER_LETTER = "COVER_LETTER"
    SUPPORTING = "SUPPORTING"


class ApplicationAnswerStatus(StrEnum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    DRAFTED = "DRAFTED"
    REVIEWED = "REVIEWED"
    PROMOTED = "PROMOTED"
    LEGACY_REVIEW_REQUIRED = "LEGACY_REVIEW_REQUIRED"


class ApplicationAnswerSource(StrEnum):
    UNANSWERED = "UNANSWERED"
    LIBRARY_REUSE = "LIBRARY_REUSE"
    GOVERNED_AI = "GOVERNED_AI"
    USER_REVIEWED = "USER_REVIEWED"
    LEGACY = "LEGACY"


class ApplicationAnswerKind(StrEnum):
    EXACT = "EXACT"
    SHORT_TEXT = "SHORT_TEXT"
    LONG_TEXT = "LONG_TEXT"
    NUMBER = "NUMBER"
    DATE = "DATE"
    YES_NO = "YES_NO"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    SALARY = "SALARY"
    AVAILABILITY = "AVAILABILITY"
    TECHNOLOGY_EXPERIENCE = "TECHNOLOGY_EXPERIENCE"
    BEHAVIORAL = "BEHAVIORAL"
    EMPLOYER_SPECIFIC = "EMPLOYER_SPECIFIC"


class PortalFieldControlKind(StrEnum):
    TEXT = "TEXT"
    TEXT_AREA = "TEXT_AREA"
    EMAIL = "EMAIL"
    TELEPHONE = "TELEPHONE"
    NUMBER = "NUMBER"
    DATE = "DATE"
    SELECT = "SELECT"
    RADIO_GROUP = "RADIO_GROUP"
    CHECKBOX = "CHECKBOX"
    FILE_UPLOAD = "FILE_UPLOAD"
    SIGNATURE = "SIGNATURE"
    DISCLOSURE = "DISCLOSURE"
    CUSTOM = "CUSTOM"


class FieldAutomationPermission(StrEnum):
    PROHIBITED = "PROHIBITED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    AUTOFILL_ALLOWED = "AUTOFILL_ALLOWED"


class FieldBindingSource(StrEnum):
    EXACT_CANONICAL_MATCH = "EXACT_CANONICAL_MATCH"
    ANSWER_QUESTION_MATCH = "ANSWER_QUESTION_MATCH"
    USER_CONFIRMED = "USER_CONFIRMED"


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(min_length=1, max_length=100)
    profile_id: str
    job_id: str
    selected_document_version_id: str | None = None


class Application(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    workflow_id: str
    profile_id: str
    job_id: str
    state: WorkflowState
    selected_document_version_id: str | None
    created_at: datetime
    updated_at: datetime


class ApplicationAnswerDraftRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    application_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=2_000)
    canonical_field: str = Field(min_length=1, max_length=160)
    answer_kind: ApplicationAnswerKind = ApplicationAnswerKind.SHORT_TEXT
    choices: list[str] = Field(default_factory=list, max_length=100)
    minimum_number: float | None = None
    maximum_number: float | None = None
    earliest_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    latest_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    character_limit: int = Field(default=20_000, ge=1, le=20_000)
    allow_ai: bool = False
    external_ai_consent: bool = False
    reuse_permission: str = Field(
        default="APPLICATIONS", pattern="^(PROFILE_ONLY|APPLICATIONS|ANY)$"
    )


class ApplicationAnswerReview(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=20_000)
    evidence_claim_ids: list[str] = Field(default_factory=list, max_length=50)
    confidence: float = Field(default=1, ge=0, le=1)
    reuse_permission: str = Field(
        default="APPLICATIONS", pattern="^(PROFILE_ONLY|APPLICATIONS|ANY)$"
    )
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class ApplicationAnswerPromotion(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_revision: int = Field(ge=1)
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class ApplicationAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    application_id: str
    profile_id: str
    job_id: str
    revision: int = Field(ge=1)
    question: str
    normalized_question: str
    canonical_field: str
    answer_kind: ApplicationAnswerKind
    validation_rules: dict[str, object]
    answer: str | None
    status: ApplicationAnswerStatus
    source_type: ApplicationAnswerSource
    source_answer_id: str | None
    library_answer_id: str | None
    evidence_claim_ids: list[str]
    retrieval_results: list[dict[str, object]]
    provider_id: str | None
    model_id: str | None
    prompt_version: str | None
    policy_version: str
    confidence: float = Field(ge=0, le=1)
    character_limit: int = Field(ge=1, le=20_000)
    character_limit_applied: bool
    limitations: list[str]
    user_edited: bool
    reuse_permission: str
    created_at: datetime
    updated_at: datetime


class ApplicationAnswerRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    application_id: str
    profile_id: str
    job_id: str
    revision: int = Field(ge=1)
    encrypted_question: str | None
    encrypted_normalized_question: str | None
    canonical_field: str
    answer_kind: ApplicationAnswerKind
    validation_rules: dict[str, object]
    encrypted_value: str
    status: ApplicationAnswerStatus
    source_type: ApplicationAnswerSource
    source_answer_id: str | None
    library_answer_id: str | None
    evidence_claim_ids: list[str]
    retrieval_results: list[dict[str, object]]
    provider_id: str | None
    model_id: str | None
    prompt_version: str | None
    policy_version: str
    confidence: float = Field(ge=0, le=1)
    encrypted_generated_value: str | None
    character_limit: int = Field(ge=1, le=20_000)
    character_limit_applied: bool
    limitations: list[str]
    user_edited: bool
    reuse_permission: str
    created_at: datetime
    updated_at: datetime


class ObservedPortalField(BaseModel):
    model_config = ConfigDict(frozen=True)

    portal: str = Field(min_length=1, max_length=80)
    page_fingerprint: str = Field(min_length=1, max_length=200)
    control_key: str = Field(min_length=1, max_length=200)
    control_kind: PortalFieldControlKind
    label: str = Field(min_length=1, max_length=500)
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=100)
    character_limit: int | None = Field(default=None, ge=1, le=20_000)
    minimum_number: float | None = None
    maximum_number: float | None = None
    earliest_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    latest_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    legal_attestation: bool = False


class ApplicationFieldBindingPreviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    application_answer_id: str = Field(min_length=1, max_length=100)
    observed_field: ObservedPortalField


class ApplicationFieldBindingApproval(ApplicationFieldBindingPreviewRequest):
    expected_answer_revision: int = Field(ge=1)
    review_fingerprint: str = Field(min_length=64, max_length=64)
    automation_permission: FieldAutomationPermission
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class ApplicationFieldBindingPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    application_id: str
    application_answer_id: str
    answer_revision: int = Field(ge=1)
    portal: str
    page_fingerprint: str
    control_key: str
    control_kind: PortalFieldControlKind
    label: str
    required: bool
    options: list[str]
    canonical_field: str
    confidence: float = Field(ge=0, le=1)
    binding_source: FieldBindingSource
    answer_source: ApplicationAnswerSource
    answer_status: ApplicationAnswerStatus
    answer_kind: ApplicationAnswerKind
    validation_rules: dict[str, object]
    compatible: bool
    validation_errors: list[str]
    proposed_permission: FieldAutomationPermission
    review_fingerprint: str = Field(min_length=64, max_length=64)


class ApplicationFieldBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    application_id: str
    application_answer_id: str
    answer_revision: int = Field(ge=1)
    portal: str
    page_fingerprint: str
    control_key: str
    control_kind: PortalFieldControlKind
    label: str
    required: bool
    options: list[str]
    canonical_field: str
    confidence: float = Field(ge=0, le=1)
    binding_source: FieldBindingSource
    answer_source: ApplicationAnswerSource
    answer_kind: ApplicationAnswerKind
    validation_rules: dict[str, object]
    automation_permission: FieldAutomationPermission
    review_fingerprint: str = Field(min_length=64, max_length=64)
    created_at: datetime
    updated_at: datetime


class ApplicationFieldBindingRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    application_id: str
    application_answer_id: str
    answer_revision: int = Field(ge=1)
    portal: str
    page_fingerprint: str
    control_key: str
    control_kind: PortalFieldControlKind
    encrypted_label: str
    encrypted_options: str
    required: bool
    canonical_field: str
    confidence: float = Field(ge=0, le=1)
    binding_source: FieldBindingSource
    answer_source: ApplicationAnswerSource
    answer_kind: ApplicationAnswerKind
    validation_rules: dict[str, object]
    automation_permission: FieldAutomationPermission
    review_fingerprint: str = Field(min_length=64, max_length=64)
    created_at: datetime
    updated_at: datetime


class SubmittedDocumentCapture(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_version_id: str = Field(min_length=1, max_length=100)
    role: ApplicationDocumentRole
    expected_sha256: str = Field(min_length=64, max_length=64)
    displayed_file_name: str = Field(min_length=1, max_length=255)
    upload_fingerprint: str = Field(min_length=1, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class SubmittedDocumentEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    application_id: str
    document_version_id: str
    role: ApplicationDocumentRole
    file_name: str
    sha256: str = Field(min_length=64, max_length=64)
    upload_fingerprint: str
    captured_at: datetime
