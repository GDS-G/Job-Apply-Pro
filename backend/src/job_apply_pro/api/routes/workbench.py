from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_apply_pro.domain.workbench import (
    MockWorkflowCreate,
    WorkflowControlCommand,
    WorkflowRunSnapshot,
)
from job_apply_pro.services.workbench import WorkbenchService, WorkbenchStateError
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    JobRepository,
    WorkbenchRepository,
)

router = APIRouter(prefix="/workbench", tags=["workbench"])
SessionDependency = Annotated[Session, Depends(get_session)]


def get_workbench_service(session: SessionDependency) -> WorkbenchService:
    return WorkbenchService(
        CandidateRepository(session),
        JobRepository(session),
        ApplicationRepository(session),
        WorkbenchRepository(session),
    )


WorkbenchDependency = Annotated[WorkbenchService, Depends(get_workbench_service)]


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, WorkbenchStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, IntegrityError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Record conflict")
    raise error


@router.post(
    "/mock-workflows",
    response_model=WorkflowRunSnapshot,
    status_code=status.HTTP_201_CREATED,
)
def start_mock_workflow(
    command: MockWorkflowCreate, service: WorkbenchDependency
) -> WorkflowRunSnapshot:
    try:
        return service.start_mock_workflow(command)
    except (LookupError, IntegrityError) as error:
        raise _http_error(error) from error


@router.get("/workflows", response_model=list[WorkflowRunSnapshot])
def list_workflows(service: WorkbenchDependency) -> list[WorkflowRunSnapshot]:
    return service.list_workflows()


@router.get("/workflows/{workflow_id}", response_model=WorkflowRunSnapshot)
def get_workflow(workflow_id: str, service: WorkbenchDependency) -> WorkflowRunSnapshot:
    try:
        return service.get_workflow(workflow_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.post("/workflows/{workflow_id}/controls", response_model=WorkflowRunSnapshot)
def control_workflow(
    workflow_id: str,
    command: WorkflowControlCommand,
    service: WorkbenchDependency,
) -> WorkflowRunSnapshot:
    try:
        return service.control_workflow(workflow_id, command)
    except (LookupError, WorkbenchStateError) as error:
        raise _http_error(error) from error
