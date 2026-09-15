"""Reviewed Greenhouse application launch contracts."""

from pydantic import BaseModel, ConfigDict, Field

from job_apply_pro.domain.browser import BrowserEngine

GREENHOUSE_APPLICATION_LAUNCH_POLICY = "reviewed-greenhouse-application-launch/1"
GREENHOUSE_APPLICATION_LAUNCH_CONFIRMATION = "OPEN REVIEWED GREENHOUSE APPLICATION"


class GreenhouseApplicationLaunchError(ValueError):
    """Safe conflict returned when reviewed launch evidence is absent or stale."""


class GreenhouseApplicationLaunchModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GreenhouseApplicationLaunchPreview(GreenhouseApplicationLaunchModel):
    application_id: str = Field(min_length=1, max_length=100)
    workflow_id: str = Field(min_length=1, max_length=100)
    profile_id: str = Field(min_length=1, max_length=100)
    job_id: str = Field(min_length=1, max_length=100)
    employer: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    start_url: str = Field(min_length=1, max_length=2_000)
    start_origin: str = Field(min_length=1, max_length=2_000)
    selected_document_version_id: str = Field(min_length=1, max_length=100)
    source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    requirements_review_id: str = Field(min_length=1, max_length=100)
    qualification_review_id: str = Field(min_length=1, max_length=100)
    selection_review_id: str = Field(min_length=1, max_length=100)
    policy_version: str
    review_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    notice: str


class GreenhouseApplicationLaunchApproval(GreenhouseApplicationLaunchModel):
    application_id: str = Field(min_length=1, max_length=100)
    review_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile_name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    engine: BrowserEngine = BrowserEngine.CHROMIUM
    confirmation_phrase: str = Field(min_length=1, max_length=100)
