from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import ValidationError
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.core import CipherDependency
from job_apply_pro.config import get_settings
from job_apply_pro.domain.job_readiness import (
    JobReadinessError,
    JobReadinessSnapshot,
    QualificationApproval,
    QualificationPreview,
    QualificationRequest,
    ReadinessSelectionPreview,
    RequirementsApproval,
    RequirementsPreview,
    RequirementsRequest,
)
from job_apply_pro.domain.knowledge import DocumentSelectionApproval, DocumentSelectionRequest
from job_apply_pro.security.encryption import DecryptionError
from job_apply_pro.security.keys import KeyConfigurationError
from job_apply_pro.services.job_readiness import JobReadinessService
from job_apply_pro.services.knowledge import CandidateKnowledgeError, CandidateKnowledgeService
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.job_readiness_repository import JobReadinessRepository
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    JobRepository,
)

router = APIRouter(
    prefix="/applications/{application_id}/job-review", tags=["reviewed-job-readiness"]
)
SessionDependency = Annotated[Session, Depends(get_session)]
ApplicationId = Annotated[str, Path(min_length=1, max_length=100)]


def get_readiness_service(
    session: SessionDependency, cipher: CipherDependency
) -> JobReadinessService:
    # This deterministic local feature must not depend on provider configuration
    # or construct an AI registry merely to review saved evidence.
    settings = get_settings()
    knowledge = CandidateKnowledgeRepository(session)
    documents = CandidateKnowledgeService(
        knowledge,
        CandidateRepository(session),
        JobRepository(session),
        ApplicationRepository(session),
        cipher,
        document_data_dir=settings.document_data_dir,
        document_max_bytes=settings.document_max_bytes,
    )
    return JobReadinessService(JobReadinessRepository(session, cipher), knowledge, documents)


ReadinessService = Annotated[JobReadinessService, Depends(get_readiness_service)]


def _run[Result](action: Callable[[], Result]) -> Result:
    try:
        return action()
    except JobReadinessError as error:
        raise HTTPException(409, str(error)) from None
    except KeyConfigurationError:
        raise HTTPException(503, "Local encryption is unavailable") from None
    except (
        CandidateKnowledgeError,
        DecryptionError,
        ValidationError,
        OSError,
        UnicodeError,
        LookupError,
    ):
        raise HTTPException(
            409, "Saved readiness evidence is unavailable or changed; reload and review"
        ) from None


def _match(application_id: str, body_id: str) -> None:
    if application_id != body_id:
        raise HTTPException(422, "Application identity must match the reviewed request")


@router.get("", response_model=JobReadinessSnapshot)
def snapshot(application_id: ApplicationId, service: ReadinessService) -> JobReadinessSnapshot:
    return _run(lambda: service.snapshot(application_id))


@router.post("/requirements/preview", response_model=RequirementsPreview)
def preview_requirements(
    application_id: ApplicationId, command: RequirementsRequest, service: ReadinessService
) -> RequirementsPreview:
    _match(application_id, command.application_id)
    return _run(lambda: service.preview_requirements(command))


@router.post("/requirements/approve", response_model=JobReadinessSnapshot)
def approve_requirements(
    application_id: ApplicationId, command: RequirementsApproval, service: ReadinessService
) -> JobReadinessSnapshot:
    _match(application_id, command.application_id)
    return _run(lambda: service.approve_requirements(command))


@router.post("/qualification/preview", response_model=QualificationPreview)
def preview_qualification(
    application_id: ApplicationId, command: QualificationRequest, service: ReadinessService
) -> QualificationPreview:
    _match(application_id, command.application_id)
    return _run(lambda: service.preview_qualification(command))


@router.post("/qualification/approve", response_model=JobReadinessSnapshot)
def approve_qualification(
    application_id: ApplicationId, command: QualificationApproval, service: ReadinessService
) -> JobReadinessSnapshot:
    _match(application_id, command.application_id)
    return _run(lambda: service.approve_qualification(command))


@router.post("/resume/preview", response_model=ReadinessSelectionPreview)
def preview_resume(
    application_id: ApplicationId, command: DocumentSelectionRequest, service: ReadinessService
) -> ReadinessSelectionPreview:
    _match(application_id, command.application_id)
    return _run(lambda: service.preview_resume(command))


@router.post("/resume/approve", response_model=JobReadinessSnapshot)
def approve_resume(
    application_id: ApplicationId, command: DocumentSelectionApproval, service: ReadinessService
) -> JobReadinessSnapshot:
    _match(application_id, command.application_id)
    return _run(lambda: service.approve_resume(command))
