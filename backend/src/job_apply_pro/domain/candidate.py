from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CandidateStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ContactDetails(BaseModel):
    model_config = ConfigDict(frozen=True)

    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)


class CandidateProfileCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    display_name: str = Field(min_length=1, max_length=200)
    contact: ContactDetails


class CandidateProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    contact: ContactDetails
    status: CandidateStatus
    created_at: datetime
    updated_at: datetime


class CandidateBackup(BaseModel):
    """Portable ciphertext; restoring requires the same master key."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    profile_id: str
    display_name: str
    encrypted_contact: str
    status: CandidateStatus
    created_at: datetime
    updated_at: datetime


class EvidenceSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    source_type: str
    source_uri: str | None = None
    content_hash: str
    created_at: datetime


class CandidateClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    evidence_source_id: str | None = None
    claim_type: str
    value: dict[str, object]
    confidence: float = Field(ge=0, le=1)
    locked: bool = False
    created_at: datetime
