from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import inspect
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
    BrowserFieldReconciliationApproval,
    BrowserFieldReconciliationPreview,
    BrowserFieldReconciliationResult,
    BrowserSessionCreate,
    BrowserSessionSnapshot,
    BrowserSessionState,
)
from job_apply_pro.domain.external_effects import ExternalEffectKind
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.services.browser_runtime import (
    BrowserPolicyError,
    BrowserRuntimeService,
    BrowserSessionStateError,
)
from job_apply_pro.services.external_effects import ExternalEffectService
from job_apply_pro.storage.database import SessionFactory, get_session
from job_apply_pro.storage.external_effect_repository import ExternalEffectRepository
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


def _external_effect_service(cipher: SensitiveDataCipher) -> ExternalEffectService:
    return ExternalEffectService(ExternalEffectRepository(SessionFactory), cipher)


def recover_browser_external_effects(cipher: SensitiveDataCipher) -> int:
    """Fence browser sessions whose prior process lost an effect response."""

    with SessionFactory() as session:
        inspector = inspect(session.get_bind())
        if not all(
            inspector.has_table(table_name)
            for table_name in (
                "external_effect_operations",
                "external_effect_attempts",
                "external_effect_reconciliations",
            )
        ):
            # The packaged desktop runs Alembic before serving. This narrow
            # compatibility path keeps standalone legacy-schema inspection and
            # isolated API tests available before that migration has run; effect
            # routes still cannot dispatch without the ledger schema.
            return 0

    effects = _external_effect_service(cipher)
    recovered = effects.recover_interrupted()
    unresolved = effects.unresolved_subject_ids(
        kind=ExternalEffectKind.BROWSER_ACTION,
        subject_type="browser_session",
    )
    with SessionFactory() as session:
        repository = BrowserRuntimeRepository(session)
        for session_id in unresolved:
            record = repository.get_record(session_id)
            if record is not None and record.state in {
                BrowserSessionState.STARTING,
                BrowserSessionState.ACTIVE,
                BrowserSessionState.USER_TAKEOVER,
            }:
                repository.set_state(session_id, BrowserSessionState.USER_TAKEOVER)
    return recovered


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
        _external_effect_service(cipher),
        browser_data_dir=settings.browser_data_dir,
        browser_artifact_dir=settings.browser_artifact_dir,
        default_headless=settings.browser_headless,
        automation_enabled=settings.automation_enabled,
    )


BrowserServiceDependency = Annotated[BrowserRuntimeService, Depends(get_browser_service)]
BrowserReconciliationId = Annotated[
    str,
    Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
]


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


@router.post(
    "/sessions/{session_id}/field-reconciliations/{operation_id}/preview",
    response_model=BrowserFieldReconciliationPreview,
)
def preview_browser_field_reconciliation(
    session_id: BrowserReconciliationId,
    operation_id: BrowserReconciliationId,
    service: BrowserServiceDependency,
) -> BrowserFieldReconciliationPreview:
    try:
        return service.preview_field_reconciliation(session_id, operation_id)
    except (LookupError, BrowserSessionStateError, BrowserWorkerError) as error:
        raise _http_error(error) from error


@router.post(
    "/sessions/{session_id}/field-reconciliations/{operation_id}/approve",
    response_model=BrowserFieldReconciliationResult,
)
def approve_browser_field_reconciliation(
    session_id: BrowserReconciliationId,
    operation_id: BrowserReconciliationId,
    approval: BrowserFieldReconciliationApproval,
    service: BrowserServiceDependency,
) -> BrowserFieldReconciliationResult:
    if approval.operation_id != operation_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Browser reconciliation operation id does not match the route",
        )
    try:
        return service.approve_field_reconciliation(session_id, approval)
    except (LookupError, BrowserSessionStateError, BrowserWorkerError) as error:
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
