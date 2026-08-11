from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from job_apply_pro.domain.workflow import WorkflowState


class CheckpointCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: WorkflowState
    page_fingerprint: str = Field(min_length=1, max_length=200)
    payload: dict[str, object]


class WorkflowCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    workflow_id: str
    sequence: int
    state: WorkflowState
    page_fingerprint: str
    payload: dict[str, object]
    created_at: datetime


class EncryptedCheckpointRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    workflow_id: str
    sequence: int
    state: WorkflowState
    page_fingerprint: str
    encrypted_payload: str
    created_at: datetime
