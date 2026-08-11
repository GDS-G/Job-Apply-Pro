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


class ApplicationAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    application_id: str
    canonical_field: CanonicalField
    value: dict[str, object]
    provenance: str
    confidence: float = Field(ge=0, le=1)
    approved: bool
    created_at: datetime
