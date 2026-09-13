"""Public discovery is not an application or an eligibility determination."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from job_apply_pro.domain.jobs import Job
from job_apply_pro.domain.workbench import WorkflowRunSnapshot

SOURCE = "greenhouse-public"


class GreenhouseBoardRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    board_token: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")

    @field_validator("board_token")
    @classmethod
    def public_board_only(cls, value: str) -> str:
        if value.casefold() == "internal":
            raise ValueError("Only external public board tokens are supported")
        return value


class GreenhouseReviewRequest(GreenhouseBoardRequest):
    posting_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")

    @field_validator("posting_id")
    @classmethod
    def bounded_posting_id(cls, value: str) -> str:
        if int(value) > 9_223_372_036_854_775_807:
            raise ValueError("Posting identifier exceeds the supported range")
        return value


class GreenhouseImportRequest(GreenhouseReviewRequest):
    review_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile_id: str = Field(min_length=1, max_length=100)


class GreenhouseJobSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    posting_id: str
    title: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    source_url: str | None
    navigation_supported: bool


class GreenhouseJobList(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    board_token: str
    board_name: str
    fetched_at: datetime
    jobs: list[GreenhouseJobSummary] = Field(max_length=1000)
    excluded_prospect_count: int = Field(ge=0)


class GreenhouseJobReview(GreenhouseJobSummary):
    board_token: str
    employer: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=50_000)
    api_url: str
    reported_url: str
    provider_updated_at: str | None
    fetched_at: datetime
    normalizer_version: str
    review_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    qualification_status: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"


class GreenhouseImportResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["IMPORTED", "EXISTING", "STALE_REVIEW", "SOURCE_CHANGED", "SOURCE_UNAVAILABLE"]
    job: Job | None = None
    workflow: WorkflowRunSnapshot | None = None
    notice: str
