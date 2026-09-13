from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from job_apply_pro.domain.workflow import WorkflowEvent, WorkflowState


class WorkflowControlAction(StrEnum):
    ADVANCE = "ADVANCE"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    RETRY = "RETRY"
    TAKEOVER = "TAKEOVER"
    STOP = "STOP"


class MockWorkflowCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str
    employer: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)


class WorkflowControlCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: WorkflowControlAction


class WorkflowRunSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str
    application_id: str
    profile_id: str
    candidate_display_name: str
    employer: str
    title: str
    state: WorkflowState
    progress: int = Field(ge=0, le=100)
    updated_at: datetime
    events: list[WorkflowEvent]
    allowed_controls: list[WorkflowControlAction] = Field(default_factory=list)


def allowed_workbench_controls(source: str, state: WorkflowState) -> list[WorkflowControlAction]:
    """The workbench state simulator must never advance real application records."""
    if source != "workbench-mock" or state is WorkflowState.CLOSED:
        return []
    if state is WorkflowState.FAILED_TERMINAL:
        return [WorkflowControlAction.STOP]
    controls = [WorkflowControlAction.RETRY, WorkflowControlAction.STOP]
    if state is WorkflowState.USER_TAKEOVER:
        controls.append(WorkflowControlAction.RESUME)
    else:
        controls.extend([WorkflowControlAction.PAUSE, WorkflowControlAction.TAKEOVER])
    if state in {
        WorkflowState.DISCOVERED,
        WorkflowState.DEDUPLICATED,
        WorkflowState.SCORED,
        WorkflowState.ELIGIBILITY_CHECKED,
        WorkflowState.DOCUMENTS_SELECTED,
        WorkflowState.APPLICATION_OPENED,
        WorkflowState.FORM_MAPPED,
        WorkflowState.ANSWERS_VALIDATED,
    }:
        controls.append(WorkflowControlAction.ADVANCE)
    return controls
