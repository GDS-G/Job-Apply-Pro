from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from job_apply_pro.domain.browser import BrowserControlKind


class GreenhouseFormStage(StrEnum):
    APPLICATION = "APPLICATION"
    DOCUMENTS = "DOCUMENTS"
    QUESTIONNAIRE = "QUESTIONNAIRE"
    REVIEW = "REVIEW"
    CONFIRMATION = "CONFIRMATION"


class GreenhouseFormAction(StrEnum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    REVIEW_FIELD = "REVIEW_FIELD"
    REVIEW_DOCUMENT_UPLOAD = "REVIEW_DOCUMENT_UPLOAD"
    USER_INTERVENTION = "USER_INTERVENTION"
    REVIEW_NAVIGATION = "REVIEW_NAVIGATION"
    FINAL_SUBMISSION_GATE = "FINAL_SUBMISSION_GATE"


class GreenhousePostconditionKind(StrEnum):
    VALUE_EQUALS = "VALUE_EQUALS"
    SELECTED_LABEL_EQUALS = "SELECTED_LABEL_EQUALS"
    CHECKED_EQUALS = "CHECKED_EQUALS"
    REQUIRED_CONSTRAINT_VALID = "REQUIRED_CONSTRAINT_VALID"
    UPLOAD_FILE_NAME_OBSERVED = "UPLOAD_FILE_NAME_OBSERVED"
    NEXT_STAGE_OBSERVED = "NEXT_STAGE_OBSERVED"
    USER_VERIFIED = "USER_VERIFIED"
    IDENTIFIER_BACKED_CONFIRMATION = "IDENTIFIER_BACKED_CONFIRMATION"


class GreenhouseControlContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_key: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=300)
    control_kind: BrowserControlKind
    required: bool
    blocking: bool
    action: GreenhouseFormAction
    postcondition: GreenhousePostconditionKind
    reason: str = Field(min_length=1, max_length=500)


class GreenhouseFormContractAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_version: str = Field(min_length=1, max_length=100)
    page_fingerprint: str = Field(min_length=1, max_length=200)
    page_type: str = Field(min_length=1, max_length=100)
    stage: GreenhouseFormStage
    required_control_count: int = Field(ge=0, le=100)
    satisfied_required_count: int = Field(ge=0, le=100)
    review_field_count: int = Field(ge=0, le=100)
    upload_review_count: int = Field(ge=0, le=100)
    manual_intervention_count: int = Field(ge=0, le=100)
    navigation_control_key: str | None = Field(default=None, max_length=200)
    navigation_label: str | None = Field(default=None, max_length=300)
    ready_to_advance: bool
    controls: list[GreenhouseControlContract] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    review_fingerprint: str = Field(min_length=64, max_length=64)


class GreenhousePostconditionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_version: str = Field(min_length=1, max_length=100)
    kind: GreenhousePostconditionKind
    before_page_fingerprint: str = Field(min_length=1, max_length=200)
    after_page_fingerprint: str = Field(min_length=1, max_length=200)
    control_key: str = Field(min_length=1, max_length=200)
    verified: bool
    reason: str = Field(min_length=1, max_length=500)
    evidence_fingerprint: str = Field(min_length=64, max_length=64)
