from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_apply_pro.domain.applications import Application, ApplicationCreate
from job_apply_pro.domain.candidate import CandidateBackup, CandidateProfile, CandidateProfileCreate
from job_apply_pro.domain.checkpoints import CheckpointCreate, WorkflowCheckpoint
from job_apply_pro.domain.jobs import Job, JobCreate
from job_apply_pro.security.encryption import DecryptionError, SensitiveDataCipher
from job_apply_pro.security.keys import EnvironmentKeyProvider, KeyConfigurationError
from job_apply_pro.services.core import CoreService, RecordNotFoundError
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    CheckpointRepository,
    JobRepository,
)

router = APIRouter(tags=["core"])
SessionDependency = Annotated[Session, Depends(get_session)]


def get_cipher() -> SensitiveDataCipher:
    return SensitiveDataCipher(EnvironmentKeyProvider())


CipherDependency = Annotated[SensitiveDataCipher, Depends(get_cipher)]


def get_core_service(session: SessionDependency, cipher: CipherDependency) -> CoreService:
    return CoreService(
        CandidateRepository(session),
        JobRepository(session),
        ApplicationRepository(session),
        CheckpointRepository(session),
        cipher,
    )


CoreServiceDependency = Annotated[CoreService, Depends(get_core_service)]


def _translate_error(error: Exception) -> HTTPException:
    if isinstance(error, RecordNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, IntegrityError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Record already exists")
    if isinstance(error, KeyConfigurationError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local encryption key is not configured",
        )
    if isinstance(error, DecryptionError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Encrypted data could not be authenticated",
        )
    raise error


@router.post("/candidates", response_model=CandidateProfile, status_code=status.HTTP_201_CREATED)
def create_candidate(
    command: CandidateProfileCreate, service: CoreServiceDependency
) -> CandidateProfile:
    try:
        return service.create_candidate(command)
    except (IntegrityError, KeyConfigurationError, DecryptionError) as error:
        raise _translate_error(error) from error


@router.get("/candidates/{profile_id}", response_model=CandidateProfile)
def get_candidate(profile_id: str, service: CoreServiceDependency) -> CandidateProfile:
    try:
        return service.get_candidate(profile_id)
    except (RecordNotFoundError, KeyConfigurationError, DecryptionError) as error:
        raise _translate_error(error) from error


@router.get("/candidates/{profile_id}/backup", response_model=CandidateBackup)
def export_candidate(profile_id: str, service: CoreServiceDependency) -> CandidateBackup:
    try:
        return service.export_candidate(profile_id)
    except (RecordNotFoundError, KeyConfigurationError, DecryptionError) as error:
        raise _translate_error(error) from error


@router.post(
    "/candidates/restore", response_model=CandidateProfile, status_code=status.HTTP_201_CREATED
)
def restore_candidate(backup: CandidateBackup, service: CoreServiceDependency) -> CandidateProfile:
    try:
        return service.restore_candidate(backup)
    except (IntegrityError, KeyConfigurationError, DecryptionError) as error:
        raise _translate_error(error) from error


@router.post("/jobs", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_job(command: JobCreate, service: CoreServiceDependency) -> Job:
    try:
        return service.create_job(command)
    except IntegrityError as error:
        raise _translate_error(error) from error


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, service: CoreServiceDependency) -> Job:
    try:
        return service.get_job(job_id)
    except RecordNotFoundError as error:
        raise _translate_error(error) from error


@router.post("/applications", response_model=Application, status_code=status.HTTP_201_CREATED)
def create_application(command: ApplicationCreate, service: CoreServiceDependency) -> Application:
    try:
        return service.create_application(command)
    except (IntegrityError, RecordNotFoundError) as error:
        raise _translate_error(error) from error


@router.get("/applications/{application_id}", response_model=Application)
def get_application(application_id: str, service: CoreServiceDependency) -> Application:
    try:
        return service.get_application(application_id)
    except RecordNotFoundError as error:
        raise _translate_error(error) from error


@router.post(
    "/workflows/{workflow_id}/checkpoints",
    response_model=WorkflowCheckpoint,
    status_code=status.HTTP_201_CREATED,
)
def save_checkpoint(
    workflow_id: str, command: CheckpointCreate, service: CoreServiceDependency
) -> WorkflowCheckpoint:
    try:
        return service.save_checkpoint(workflow_id, command)
    except (IntegrityError, KeyConfigurationError, DecryptionError) as error:
        raise _translate_error(error) from error


@router.get("/workflows/{workflow_id}/checkpoints/latest", response_model=WorkflowCheckpoint)
def latest_checkpoint(workflow_id: str, service: CoreServiceDependency) -> WorkflowCheckpoint:
    try:
        return service.latest_checkpoint(workflow_id)
    except (RecordNotFoundError, KeyConfigurationError, DecryptionError) as error:
        raise _translate_error(error) from error
