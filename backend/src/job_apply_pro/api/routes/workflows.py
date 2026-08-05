from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from job_apply_pro.domain.workflow import InvalidTransitionError, TransitionCommand, WorkflowEvent
from job_apply_pro.services.workflows import WorkflowService
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.repositories import WorkflowEventRepository

router = APIRouter(prefix="/workflows", tags=["workflows"])


SessionDependency = Annotated[Session, Depends(get_session)]


def get_workflow_service(session: SessionDependency) -> WorkflowService:
    return WorkflowService(WorkflowEventRepository(session))


WorkflowServiceDependency = Annotated[WorkflowService, Depends(get_workflow_service)]


@router.post(
    "/{workflow_id}/transitions",
    response_model=WorkflowEvent,
    status_code=status.HTTP_201_CREATED,
)
def transition_workflow(
    workflow_id: str,
    command: TransitionCommand,
    service: WorkflowServiceDependency,
) -> WorkflowEvent:
    try:
        return service.transition(workflow_id, command)
    except InvalidTransitionError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/{workflow_id}/events", response_model=list[WorkflowEvent])
def workflow_events(
    workflow_id: str,
    service: WorkflowServiceDependency,
) -> list[WorkflowEvent]:
    return service.history(workflow_id)
