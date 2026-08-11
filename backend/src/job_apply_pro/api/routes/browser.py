from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from job_apply_pro.browser.client import (
    BrowserWorkerClient,
    BrowserWorkerError,
    BrowserWorkerUnavailableError,
)
from job_apply_pro.config import get_settings
from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionResult,
    BrowserSessionCreate,
    BrowserSessionSnapshot,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.services.browser_runtime import (
    BrowserPolicyError,
    BrowserRuntimeService,
    BrowserSessionStateError,
)
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.repositories import (
    BrowserRuntimeRepository,
    CheckpointRepository,
    WorkbenchRepository,
)

from .core import get_cipher

router = APIRouter(prefix="/browser", tags=["browser"])
SessionDependency = Annotated[Session, Depends(get_session)]
CipherDependency = Annotated[SensitiveDataCipher, Depends(get_cipher)]
_worker = BrowserWorkerClient()


def shutdown_browser_worker() -> None:
    _worker.close()


def get_browser_service(
    session: SessionDependency, cipher: CipherDependency
) -> BrowserRuntimeService:
    settings = get_settings()
    return BrowserRuntimeService(
        BrowserRuntimeRepository(session),
        WorkbenchRepository(session),
        CheckpointRepository(session),
        cipher,
        _worker,
        browser_data_dir=settings.browser_data_dir,
        browser_artifact_dir=settings.browser_artifact_dir,
        default_headless=settings.browser_headless,
        automation_enabled=settings.automation_enabled,
    )


BrowserServiceDependency = Annotated[BrowserRuntimeService, Depends(get_browser_service)]


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, BrowserPolicyError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    if isinstance(error, BrowserSessionStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, BrowserWorkerUnavailableError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser worker is unavailable; saved checkpoints were preserved",
        )
    if isinstance(error, BrowserWorkerError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    raise error


@router.post(
    "/sessions",
    response_model=BrowserSessionSnapshot,
    status_code=status.HTTP_201_CREATED,
)
def create_browser_session(
    command: BrowserSessionCreate, service: BrowserServiceDependency
) -> BrowserSessionSnapshot:
    try:
        return service.create_session(command)
    except (LookupError, BrowserPolicyError, BrowserSessionStateError, BrowserWorkerError) as error:
        raise _http_error(error) from error


@router.get("/sessions", response_model=list[BrowserSessionSnapshot])
def list_browser_sessions(
    service: BrowserServiceDependency,
    workflow_id: Annotated[str | None, Query(max_length=100)] = None,
) -> list[BrowserSessionSnapshot]:
    return service.list_sessions(workflow_id)


@router.get("/sessions/{session_id}", response_model=BrowserSessionSnapshot)
def get_browser_session(
    session_id: str, service: BrowserServiceDependency
) -> BrowserSessionSnapshot:
    try:
        return service.get_session(session_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.post("/sessions/{session_id}/observe", response_model=BrowserSessionSnapshot)
def observe_browser_session(
    session_id: str, service: BrowserServiceDependency
) -> BrowserSessionSnapshot:
    try:
        return service.observe(session_id)
    except (LookupError, BrowserSessionStateError, BrowserWorkerError) as error:
        raise _http_error(error) from error


@router.post("/sessions/{session_id}/actions", response_model=BrowserActionResult)
def execute_browser_action(
    session_id: str,
    action: BrowserAction,
    service: BrowserServiceDependency,
) -> BrowserActionResult:
    try:
        return service.execute_action(session_id, action)
    except (
        LookupError,
        BrowserPolicyError,
        BrowserSessionStateError,
        BrowserWorkerError,
    ) as error:
        raise _http_error(error) from error


@router.get("/sessions/{session_id}/actions", response_model=list[BrowserActionResult])
def list_browser_actions(
    session_id: str, service: BrowserServiceDependency
) -> list[BrowserActionResult]:
    try:
        return service.list_actions(session_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.post("/sessions/{session_id}/takeover", response_model=BrowserSessionSnapshot)
def takeover_browser_session(
    session_id: str, service: BrowserServiceDependency
) -> BrowserSessionSnapshot:
    try:
        return service.takeover(session_id)
    except (LookupError, BrowserSessionStateError) as error:
        raise _http_error(error) from error


@router.post("/sessions/{session_id}/resume", response_model=BrowserSessionSnapshot)
def resume_browser_session(
    session_id: str, service: BrowserServiceDependency
) -> BrowserSessionSnapshot:
    try:
        return service.resume(session_id)
    except (LookupError, BrowserSessionStateError, BrowserWorkerError) as error:
        raise _http_error(error) from error


@router.post("/sessions/{session_id}/restart", response_model=BrowserSessionSnapshot)
def restart_browser_session(
    session_id: str, service: BrowserServiceDependency
) -> BrowserSessionSnapshot:
    try:
        return service.restart(session_id)
    except (LookupError, BrowserSessionStateError, BrowserWorkerError) as error:
        raise _http_error(error) from error


@router.post("/sessions/{session_id}/stop", response_model=BrowserSessionSnapshot)
def stop_browser_session(
    session_id: str, service: BrowserServiceDependency
) -> BrowserSessionSnapshot:
    try:
        return service.stop(session_id)
    except (LookupError, BrowserSessionStateError, BrowserWorkerError) as error:
        raise _http_error(error) from error
