from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class InvocationStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ModelInvocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    task_type: str
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    input_hash: str
    status: InvocationStatus
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_micros: int = Field(default=0, ge=0)
    created_at: datetime


class ErrorClassification(StrEnum):
    RETRYABLE = "RETRYABLE"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    TERMINAL = "TERMINAL"


class ErrorRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    workflow_id: str | None = None
    classification: ErrorClassification
    component: str
    action: str
    sanitized_context: dict[str, object]
    retry_count: int = Field(default=0, ge=0, le=20)
    created_at: datetime
