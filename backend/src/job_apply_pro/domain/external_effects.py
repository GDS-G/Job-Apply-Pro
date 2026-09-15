from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExternalEffectKind(StrEnum):
    BROWSER_ACTION = "BROWSER_ACTION"
    AI_COMPLETION = "AI_COMPLETION"
    AI_EMBEDDING = "AI_EMBEDDING"
    CALENDAR_UPDATE = "CALENDAR_UPDATE"


class ExternalEffectStatus(StrEnum):
    PREPARED = "PREPARED"
    DISPATCHING = "DISPATCHING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


class ExternalEffectReconciliationKind(StrEnum):
    BROWSER_FIELD_VALUE_CONFIRMED = "BROWSER_FIELD_VALUE_CONFIRMED"
    BROWSER_NAVIGATION_CONFIRMED = "BROWSER_NAVIGATION_CONFIRMED"
    BROWSER_UPLOAD_CONFIRMED = "BROWSER_UPLOAD_CONFIRMED"


class ExternalEffectReconciliationStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    CONFIRMED_APPLIED = "CONFIRMED_APPLIED"


TERMINAL_EXTERNAL_EFFECT_STATUSES = {
    ExternalEffectStatus.CONFIRMED,
    ExternalEffectStatus.FAILED,
    ExternalEffectStatus.UNCERTAIN,
}

_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
_FINGERPRINT_PATTERN = r"^[a-f0-9]{64}$"
_SAFE_REFERENCE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$"
_SAFE_CODE_PATTERN = r"^[A-Z][A-Z0-9_]{0,79}$"


class ExternalEffectOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=_ID_PATTERN)
    claim_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    kind: ExternalEffectKind
    subject_type: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    subject_id: str = Field(pattern=_SAFE_REFERENCE_PATTERN)
    actor: str = Field(pattern=_SAFE_REFERENCE_PATTERN)
    request_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    policy_version: str = Field(pattern=_SAFE_REFERENCE_PATTERN)
    status: ExternalEffectStatus
    result_reference: str | None = Field(default=None, pattern=_SAFE_REFERENCE_PATTERN)
    result_fingerprint: str | None = Field(default=None, pattern=_FINGERPRINT_PATTERN)
    error_code: str | None = Field(default=None, pattern=_SAFE_CODE_PATTERN)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @field_validator("created_at", "updated_at", "completed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("External-effect timestamps must be timezone-aware")
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ExternalEffectOperation":
        terminal = self.status in TERMINAL_EXTERNAL_EFFECT_STATUSES
        if terminal != (self.completed_at is not None):
            raise ValueError("Only terminal external effects have completion timestamps")
        if self.status is ExternalEffectStatus.CONFIRMED:
            if self.result_reference is None or self.result_fingerprint is None or self.error_code:
                raise ValueError("Confirmed external effects require a safe result and no error")
        elif self.status in {ExternalEffectStatus.FAILED, ExternalEffectStatus.UNCERTAIN}:
            if self.error_code is None or self.result_reference or self.result_fingerprint:
                raise ValueError(
                    "Failed or uncertain external effects require only a safe error code"
                )
        elif self.result_reference or self.result_fingerprint or self.error_code:
            raise ValueError("Active external effects cannot have terminal outcome fields")
        return self


class ExternalEffectAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=_ID_PATTERN)
    operation_id: str = Field(pattern=_ID_PATTERN)
    sequence: int = Field(ge=1, le=100)
    provider: str = Field(pattern=_SAFE_REFERENCE_PATTERN)
    target_code: str = Field(pattern=_SAFE_REFERENCE_PATTERN)
    request_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    native_key_fingerprint: str | None = Field(default=None, pattern=_FINGERPRINT_PATTERN)
    status: ExternalEffectStatus
    result_reference: str | None = Field(default=None, pattern=_SAFE_REFERENCE_PATTERN)
    result_fingerprint: str | None = Field(default=None, pattern=_FINGERPRINT_PATTERN)
    error_code: str | None = Field(default=None, pattern=_SAFE_CODE_PATTERN)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_micros: int | None = Field(default=None, ge=0)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @field_validator("created_at", "updated_at", "completed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("External-effect timestamps must be timezone-aware")
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ExternalEffectAttempt":
        terminal = self.status in TERMINAL_EXTERNAL_EFFECT_STATUSES
        if terminal != (self.completed_at is not None):
            raise ValueError("Only terminal external-effect attempts have completion timestamps")
        if self.status is ExternalEffectStatus.CONFIRMED:
            if self.result_reference is None or self.result_fingerprint is None or self.error_code:
                raise ValueError("Confirmed attempts require a safe result and no error")
        elif self.status in {ExternalEffectStatus.FAILED, ExternalEffectStatus.UNCERTAIN}:
            if self.error_code is None or self.result_reference or self.result_fingerprint:
                raise ValueError("Failed or uncertain attempts require only a safe error code")
        elif self.result_reference or self.result_fingerprint or self.error_code:
            raise ValueError("Active attempts cannot have terminal outcome fields")
        return self


class ExternalEffectReconciliation(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation_id: str = Field(pattern=_ID_PATTERN)
    attempt_id: str = Field(pattern=_ID_PATTERN)
    kind: ExternalEffectReconciliationKind
    status: ExternalEffectReconciliationStatus
    encrypted_payload: str = Field(min_length=1)
    source_page_fingerprint: str = Field(pattern=_SAFE_REFERENCE_PATTERN)
    evidence_reference: str | None = Field(default=None, pattern=_SAFE_REFERENCE_PATTERN)
    evidence_fingerprint: str | None = Field(default=None, pattern=_FINGERPRINT_PATTERN)
    result_page_fingerprint: str | None = Field(default=None, pattern=_SAFE_REFERENCE_PATTERN)
    policy_version: str = Field(pattern=_SAFE_REFERENCE_PATTERN)
    actor: str = Field(pattern=_SAFE_REFERENCE_PATTERN)
    created_at: datetime
    reconciled_at: datetime | None = None

    @field_validator("created_at", "reconciled_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("External-effect reconciliation timestamp must be timezone-aware")
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ExternalEffectReconciliation":
        terminal = self.status is ExternalEffectReconciliationStatus.CONFIRMED_APPLIED
        fields = (
            self.evidence_reference,
            self.evidence_fingerprint,
            self.result_page_fingerprint,
            self.reconciled_at,
        )
        if terminal != all(value is not None for value in fields):
            raise ValueError("Only confirmed reconciliation has complete terminal evidence")
        if not terminal and any(value is not None for value in fields):
            raise ValueError("Available reconciliation intent cannot have outcome evidence")
        return self


class ExternalEffectAdmission(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: ExternalEffectOperation
    created: bool


class ExternalEffectRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: ExternalEffectOperation
    attempts: list[ExternalEffectAttempt]
    reconciliation: ExternalEffectReconciliation | None = None


class ExternalEffectPublicRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=_ID_PATTERN)
    kind: ExternalEffectKind
    subject_type: str
    subject_id: str
    status: ExternalEffectStatus
    result_reference: str | None = None
    error_code: str | None = None
    attempt_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    reconciliation_available: bool = False
    reconciliation_kind: ExternalEffectReconciliationKind | None = None
    reconciled_at: datetime | None = None


class ExternalEffectMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int = Field(ge=0)
    unresolved: int = Field(ge=0)
    by_status: dict[ExternalEffectStatus, int] = Field(default_factory=dict)
    by_kind: dict[ExternalEffectKind, int] = Field(default_factory=dict)
