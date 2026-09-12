from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MediaCleanupState(StrEnum):
    UPLOADING = "UPLOADING"
    IN_USE = "IN_USE"
    DELETE_PENDING = "DELETE_PENDING"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    DELETED = "DELETED"


class MediaCleanupPublicRecord(BaseModel):
    """Sanitized retention status; never includes remote identifiers or credentials."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    provider_id: str
    state: MediaCleanupState
    known_resource: bool
    attempts: int = Field(ge=0)
    reason: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    lease_until: datetime | None = None
    next_attempt_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MediaCleanupRecord(MediaCleanupPublicRecord):
    """Internal ownership record; candidate listings deliberately omit decrypted names."""

    account_fingerprint: str
    owner_token: str
    resource_name: str | None = None
