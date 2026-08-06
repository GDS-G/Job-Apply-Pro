from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.core import get_cipher
from job_apply_pro.config import get_settings
from job_apply_pro.domain.operations import (
    BackupCreate,
    BackupManifest,
    BackupSchedule,
    BackupScheduleCreate,
    BackupVerification,
    HelpTopic,
    LicenseState,
    OperationsDashboard,
    RestoreCreate,
    RestorePlan,
)
from job_apply_pro.domain.support import SupportDiagnostics
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.services.backup import BackupError, BackupService
from job_apply_pro.services.licensing import LicenseService, help_topics
from job_apply_pro.services.operations import OperationsService
from job_apply_pro.services.support import SupportService
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.operations_repository import OperationsRepository
from job_apply_pro.storage.support_repository import SupportRepository

router = APIRouter(prefix="/operations", tags=["operations"])
SessionDependency = Annotated[Session, Depends(get_session)]
CipherDependency = Annotated[SensitiveDataCipher, Depends(get_cipher)]


def get_backup_service(session: SessionDependency, cipher: CipherDependency) -> BackupService:
    settings = get_settings()
    return BackupService(
        OperationsRepository(session),
        cipher,
        database_url=settings.database_url,
        document_dir=settings.document_data_dir,
        backup_dir=settings.backup_data_dir,
        staging_dir=settings.restore_staging_dir,
    )


def get_operations_service(
    session: SessionDependency, cipher: CipherDependency
) -> OperationsService:
    settings = get_settings()
    return OperationsService(
        OperationsRepository(session),
        CommunicationRepository(session, cipher),
        LicenseService(settings.license_public_key, settings.signed_license_json),
    )


BackupServiceDependency = Annotated[BackupService, Depends(get_backup_service)]
OperationsServiceDependency = Annotated[OperationsService, Depends(get_operations_service)]


def get_support_service(session: SessionDependency, cipher: CipherDependency) -> SupportService:
    settings = get_settings()
    operations = OperationsRepository(session)
    backups = BackupService(
        operations,
        cipher,
        database_url=settings.database_url,
        document_dir=settings.document_data_dir,
        backup_dir=settings.backup_data_dir,
        staging_dir=settings.restore_staging_dir,
    )
    return SupportService(SupportRepository(session), operations, backups, settings)


SupportServiceDependency = Annotated[SupportService, Depends(get_support_service)]


def _backup_error(error: Exception) -> HTTPException:
    if isinstance(error, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Backup or restore integrity validation failed",
    )


@router.get("/dashboard", response_model=OperationsDashboard)
def dashboard(service: OperationsServiceDependency) -> OperationsDashboard:
    return service.dashboard()


@router.get("/backups", response_model=list[BackupManifest])
def list_backups(service: BackupServiceDependency) -> list[BackupManifest]:
    return service.list_backups()


@router.post("/backups", response_model=BackupManifest, status_code=201)
def create_backup(command: BackupCreate, service: BackupServiceDependency) -> BackupManifest:
    try:
        return service.create(command)
    except (BackupError, ValueError) as error:
        raise _backup_error(error) from error


@router.get("/backup-schedules", response_model=list[BackupSchedule])
def list_backup_schedules(service: BackupServiceDependency) -> list[BackupSchedule]:
    return service.list_schedules()


@router.post("/backup-schedules", response_model=BackupSchedule, status_code=201)
def create_backup_schedule(
    command: BackupScheduleCreate, service: BackupServiceDependency
) -> BackupSchedule:
    try:
        return service.create_schedule(command)
    except ValueError as error:
        raise _backup_error(error) from error


@router.post("/backup-schedules/run-due", response_model=list[BackupManifest])
def run_due_backup_schedules(service: BackupServiceDependency) -> list[BackupManifest]:
    try:
        return service.run_due_schedules()
    except (BackupError, ValueError) as error:
        raise _backup_error(error) from error


@router.post("/backups/{backup_id}/verify", response_model=BackupVerification)
def verify_backup(backup_id: str, service: BackupServiceDependency) -> BackupVerification:
    try:
        return service.verify(backup_id)
    except (BackupError, LookupError, ValueError) as error:
        raise _backup_error(error) from error


@router.post("/backups/{backup_id}/restore-plans", response_model=RestorePlan, status_code=201)
def stage_restore(
    backup_id: str, command: RestoreCreate, service: BackupServiceDependency
) -> RestorePlan:
    try:
        return service.stage_restore(backup_id, command)
    except (BackupError, LookupError, ValueError) as error:
        raise _backup_error(error) from error


@router.get("/license", response_model=LicenseState)
def license_state() -> LicenseState:
    settings = get_settings()
    return LicenseService(settings.license_public_key, settings.signed_license_json).state()


@router.get("/help", response_model=list[HelpTopic])
def get_help_topics() -> list[HelpTopic]:
    return help_topics()


@router.get("/diagnostics", response_model=SupportDiagnostics)
def support_diagnostics(service: SupportServiceDependency) -> SupportDiagnostics:
    return service.diagnostics()
