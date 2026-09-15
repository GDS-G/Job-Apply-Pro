from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import ValidationError
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.core import CipherDependency
from job_apply_pro.api.routes.portals import get_supervised_portal_service
from job_apply_pro.browser.client import BrowserWorkerError, BrowserWorkerUnavailableError
from job_apply_pro.config import get_settings
from job_apply_pro.domain.greenhouse_application import (
    GreenhouseApplicationLaunchApproval,
    GreenhouseApplicationLaunchError,
    GreenhouseApplicationLaunchPreview,
)
from job_apply_pro.domain.greenhouse_form import (
    GreenhouseFormActionApproval,
    GreenhouseFormActionPreview,
    GreenhouseFormActionRequest,
)
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
from job_apply_pro.domain.portals import SupervisedPortalRunSnapshot
from job_apply_pro.security.encryption import DecryptionError
from job_apply_pro.security.keys import KeyConfigurationError
from job_apply_pro.services.browser_runtime import BrowserPolicyError, BrowserSessionStateError
from job_apply_pro.services.greenhouse_application import GreenhouseApplicationService
from job_apply_pro.services.job_readiness import JobReadinessService
from job_apply_pro.services.knowledge import CandidateKnowledgeError, CandidateKnowledgeService
from job_apply_pro.services.supervised_portals import (
    SupervisedPortalPolicyError,
    SupervisedPortalService,
    SupervisedPortalStateError,
)
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


def get_greenhouse_application_preview_service(
    readiness: ReadinessService,
) -> GreenhouseApplicationService:
    # Preview is deterministic and must remain available while browser execution
    # is disabled or unavailable.
    return GreenhouseApplicationService(readiness)


GreenhouseApplicationPreviewServiceDependency = Annotated[
    GreenhouseApplicationService,
    Depends(get_greenhouse_application_preview_service),
]


def get_greenhouse_application_service(
    readiness: ReadinessService,
    session: SessionDependency,
    supervised: Annotated[
        SupervisedPortalService,
        Depends(get_supervised_portal_service),
    ],
) -> GreenhouseApplicationService:
    return GreenhouseApplicationService(
        readiness,
        supervised,
        CandidateKnowledgeRepository(session),
    )


GreenhouseApplicationServiceDependency = Annotated[
    GreenhouseApplicationService, Depends(get_greenhouse_application_service)
]


def _run[Result](action: Callable[[], Result]) -> Result:
    try:
        return action()
    except (JobReadinessError, GreenhouseApplicationLaunchError) as error:
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


@router.get(
    "/greenhouse-launch",
    response_model=GreenhouseApplicationLaunchPreview,
)
def preview_greenhouse_application_launch(
    application_id: ApplicationId,
    service: GreenhouseApplicationPreviewServiceDependency,
) -> GreenhouseApplicationLaunchPreview:
    return _run(lambda: service.preview(application_id))


@router.post(
    "/greenhouse-launch",
    response_model=SupervisedPortalRunSnapshot,
    status_code=201,
)
def start_greenhouse_application_launch(
    application_id: ApplicationId,
    command: GreenhouseApplicationLaunchApproval,
    service: GreenhouseApplicationServiceDependency,
) -> SupervisedPortalRunSnapshot:
    _match(application_id, command.application_id)
    try:
        return _run(lambda: service.start(command))
    except SupervisedPortalPolicyError as error:
        raise HTTPException(403, str(error)) from None
    except (SupervisedPortalStateError, BrowserSessionStateError) as error:
        raise HTTPException(409, str(error)) from None
    except BrowserPolicyError as error:
        raise HTTPException(403, str(error)) from None
    except BrowserWorkerUnavailableError:
        raise HTTPException(503, "Browser worker is unavailable") from None
    except BrowserWorkerError:
        raise HTTPException(422, "The supervised browser could not be started") from None


@router.post(
    "/greenhouse-form-actions/preview",
    response_model=GreenhouseFormActionPreview,
)
def preview_greenhouse_form_action(
    application_id: ApplicationId,
    command: GreenhouseFormActionRequest,
    service: GreenhouseApplicationServiceDependency,
) -> GreenhouseFormActionPreview:
    _match(application_id, command.application_id)
    return _run(lambda: service.preview_form_action(command))


@router.post(
    "/greenhouse-form-actions/execute",
    response_model=SupervisedPortalRunSnapshot,
)
def execute_greenhouse_form_action(
    application_id: ApplicationId,
    approval: GreenhouseFormActionApproval,
    service: GreenhouseApplicationServiceDependency,
) -> SupervisedPortalRunSnapshot:
    _match(application_id, approval.application_id)
    try:
        return _run(lambda: service.execute_form_action(approval))
    except SupervisedPortalPolicyError as error:
        raise HTTPException(403, str(error)) from None
    except (SupervisedPortalStateError, BrowserSessionStateError) as error:
        raise HTTPException(409, str(error)) from None
    except BrowserPolicyError as error:
        raise HTTPException(403, str(error)) from None
    except BrowserWorkerUnavailableError:
        raise HTTPException(503, "Browser worker is unavailable") from None
    except BrowserWorkerError:
        raise HTTPException(422, "The reviewed Greenhouse action could not be completed") from None
