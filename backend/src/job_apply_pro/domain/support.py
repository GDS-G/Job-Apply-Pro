from datetime import datetime

from pydantic import BaseModel, ConfigDict

from job_apply_pro.domain.operations import ModelCostMetrics, PortalHealthMetric


class QueueHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    active: int
    retryable: int
    terminal: int


class RecoveryHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    retried_actions: int
    recovered_actions: int
    recovery_rate: float
    checkpoint_count: int


class SessionHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    active: int
    takeover: int
    stopped: int
    failed: int


class StorageHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_bytes: int
    documents_bytes: int
    browser_artifacts_bytes: int
    backups_bytes: int
    restore_staging_bytes: int


class SanitizedErrorSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    classification: str
    component: str
    action: str
    retry_count: int
    context_keys: list[str]
    created_at: datetime


class WorkflowDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str
    state: str
    event_count: int
    updated_at: datetime


class TraceDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str
    file_name: str
    size_bytes: int
    available: bool


class SupportDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    application_version: str
    build_name: str
    schema_revision: str
    environment: str
    process_status: str
    queue: QueueHealth
    recovery: RecoveryHealth
    sessions: SessionHealth
    storage: StorageHealth
    backups_total: int
    latest_backup_status: str | None
    models: ModelCostMetrics
    portals: list[PortalHealthMetric]
    workflows: list[WorkflowDiagnostic]
    errors: list[SanitizedErrorSummary]
    traces: list[TraceDiagnostic]
    update_status: str = "MANAGED_BY_DESKTOP"
    redaction_policy_version: str = "1.0.0"
