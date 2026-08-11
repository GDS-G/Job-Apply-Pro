from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BackupCategory(StrEnum):
    DATABASE = "DATABASE"
    DOCUMENTS = "DOCUMENTS"


class BackupStatus(StrEnum):
    CREATING = "CREATING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class RestoreStatus(StrEnum):
    STAGED = "STAGED"
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class LicenseStatus(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    ACTIVE = "ACTIVE"
    GRACE_PERIOD = "GRACE_PERIOD"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class BackupCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    categories: set[BackupCategory] = Field(
        default_factory=lambda: {BackupCategory.DATABASE, BackupCategory.DOCUMENTS}
    )
    label: str = Field(default="Manual backup", min_length=1, max_length=200)


class BackupEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: BackupCategory
    relative_path: str = Field(min_length=1, max_length=1_000)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)


class BackupManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    format_version: int = 1
    application_version: str
    schema_revision: str
    label: str
    categories: set[BackupCategory]
    entries: list[BackupEntry]
    encryption_key_id: str
    archive_path: str
    archive_sha256: str = Field(min_length=64, max_length=64)
    archive_size_bytes: int = Field(ge=0)
    status: BackupStatus
    created_at: datetime
    verified_at: datetime | None = None


class BackupVerification(BaseModel):
    model_config = ConfigDict(frozen=True)

    backup_id: str
    valid: bool
    reasons: list[str]
    verified_entries: int = Field(ge=0)
    verified_at: datetime


class BackupScheduleCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1, max_length=200)
    categories: set[BackupCategory]
    interval_hours: int = Field(ge=1, le=720)
    enabled: bool = True


class BackupSchedule(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    categories: set[BackupCategory]
    interval_hours: int
    enabled: bool
    next_run_at: datetime
    last_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RestoreCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    categories: set[BackupCategory]


class RestorePlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    backup_id: str
    categories: set[BackupCategory]
    staged_path: str
    file_count: int = Field(ge=0)
    fingerprint: str = Field(min_length=64, max_length=64)
    status: RestoreStatus
    created_at: datetime
    applied_at: datetime | None = None


class RestoreConfirmation(BaseModel):
    model_config = ConfigDict(frozen=True)

    fingerprint: str = Field(min_length=64, max_length=64)
    confirmation_phrase: str


class ApplicationMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    jobs_discovered: int = 0
    applications_total: int = 0
    submission_attempted: int = 0
    submission_confirmed: int = 0
    tracking_active: int = 0
    failed: int = 0
    duplicated: int = 0
    interviews_received: int = 0
    offers_received: int = 0
    recruiter_messages: int = 0


class ModelCostMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    invocations: int = 0
    successful: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
    average_latency_ms: float = 0
    by_provider: dict[str, int] = Field(default_factory=dict)


class PortalHealthMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    portal: str
    support_status: str
    production_enabled: bool
    run_count: int
    replay_validated_page_types: list[str]
    live_validated_page_types: list[str]
    limitations: list[str]


class ApplicationReportRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str
    employer: str
    title: str
    state: str
    submission_attempted: bool
    submission_confirmed: bool
    updated_at: datetime


class InterviewReportRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    communication_id: str
    workflow_id: str | None
    category: str
    sender: str
    subject: str
    received_at: datetime


class OperationsDashboard(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    applications: ApplicationMetrics
    models: ModelCostMetrics
    portals: list[PortalHealthMetric]
    application_report: list[ApplicationReportRow]
    interview_report: list[InterviewReportRow]
    backup_count: int
    latest_backup: BackupManifest | None = None
    license: "LicenseState"


class LicenseEntitlement(BaseModel):
    model_config = ConfigDict(frozen=True)

    license_id: str
    subject: str
    device_public_key: str
    features: list[str]
    issued_at: datetime
    expires_at: datetime
    offline_grace_days: int = Field(default=7, ge=0, le=90)


class SignedLicense(BaseModel):
    model_config = ConfigDict(frozen=True)

    payload: str
    signature: str


class LicenseState(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: LicenseStatus
    message: str
    entitlement: LicenseEntitlement | None = None
    recovery_allowed: bool = True
    payment_enabled: bool = False


class HelpTopic(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    summary: str
    steps: list[str]
    context: str


OperationsDashboard.model_rebuild()
