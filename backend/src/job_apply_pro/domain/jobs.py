from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class JobCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str = Field(min_length=1, max_length=80)
    external_id: str = Field(min_length=1, max_length=200)
    employer: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    source_url: AnyHttpUrl | None = None
    description_hash: str = Field(min_length=64, max_length=64)


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    source: str
    external_id: str
    employer: str
    title: str
    location: str | None
    source_url: str | None
    description_hash: str
    discovered_at: datetime


class JobRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    job_id: str
    category: str
    text: str
    required: bool
    evidence: dict[str, object]


class FitScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    job_id: str
    profile_id: str
    score: float = Field(ge=0, le=1)
    explanation: dict[str, object]
    model_version: str
    created_at: datetime
