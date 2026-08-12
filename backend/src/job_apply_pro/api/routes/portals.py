from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.browser import get_browser_service
from job_apply_pro.browser.client import BrowserWorkerError, BrowserWorkerUnavailableError
from job_apply_pro.config import get_settings
from job_apply_pro.domain.applications import (
    ApplicationFieldCoverageReview,
    ApplicationFieldExecution,
    ApplicationFieldExecutionApproval,
)
from job_apply_pro.domain.browser import BrowserEngine
from job_apply_pro.domain.portals import (
    PortalAdapterDefinition,
    PortalKind,
    PortalPageMatch,
    PortalPageProbe,
    PortalRegressionMetric,
    PortalReplayCase,
    PortalRunSnapshot,
    ReferencePortalRunCreate,
    SubmissionApproval,
    SupervisedPortalCapture,
    SupervisedPortalRunCreate,
    SupervisedPortalRunSnapshot,
    SupervisedPortalSubmissionApproval,
)
from job_apply_pro.portals.catalog import PortalCatalog, PortalCatalogError
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.services.browser_runtime import BrowserPolicyError, BrowserSessionStateError
from job_apply_pro.services.core import CoreService
from job_apply_pro.services.field_bindings import ApplicationFieldBindingService
from job_apply_pro.services.field_coverage import ApplicationFieldCoverageService
from job_apply_pro.services.field_execution import (
    ApplicationFieldExecutionService,
    FieldExecutionConflictError,
    FieldExecutionError,
    FieldExecutionPolicyError,
)
from job_apply_pro.services.portals import (
    PortalApprovalError,
    PortalEligibilityError,
    PortalExecutionError,
    ReferencePortalService,
)
from job_apply_pro.services.supervised_portals import (
    SupervisedPortalPolicyError,
    SupervisedPortalService,
    SupervisedPortalStateError,
    parse_portal_allowlist,
)
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.field_binding_repository import (
    ApplicationFieldBindingRepository,
    ApplicationFieldExecutionRepository,
)
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    CheckpointRepository,
    JobRepository,
    PortalRunRepository,
    WorkbenchRepository,
)
from job_apply_pro.storage.supervised_portal_repository import SupervisedPortalRepository

from .core import get_cipher

router = APIRouter(prefix="/portals", tags=["portals"])
SessionDependency = Annotated[Session, Depends(get_session)]
CipherDependency = Annotated[SensitiveDataCipher, Depends(get_cipher)]


def get_portal_service(
    session: SessionDependency, cipher: CipherDependency
) -> ReferencePortalService:
    candidates = CandidateRepository(session)
    jobs = JobRepository(session)
    applications = ApplicationRepository(session)
    checkpoints = CheckpointRepository(session)
    workbench = WorkbenchRepository(session)
    core = CoreService(candidates, jobs, applications, checkpoints, cipher)
    return ReferencePortalService(
        core=core,
        jobs=jobs,
        applications=applications,
        workbench=workbench,
        knowledge=CandidateKnowledgeRepository(session),
        runs=PortalRunRepository(session),
        browser=get_browser_service(session, cipher),
        cipher=cipher,
        default_browser_engine=BrowserEngine(get_settings().browser_engine),
    )


PortalServiceDependency = Annotated[ReferencePortalService, Depends(get_portal_service)]


def get_portal_catalog() -> PortalCatalog:
    return PortalCatalog()


PortalCatalogDependency = Annotated[PortalCatalog, Depends(get_portal_catalog)]


def get_supervised_portal_service(
    session: SessionDependency,
    cipher: CipherDependency,
    catalog: PortalCatalogDependency,
) -> SupervisedPortalService:
    settings = get_settings()
    return SupervisedPortalService(
        SupervisedPortalRepository(session),
        get_browser_service(session, cipher),
        catalog,
        enabled=settings.supervised_portal_enabled,
        submission_enabled=settings.supervised_portal_submission_enabled,
        allowed_portals=parse_portal_allowlist(settings.supervised_portal_allowlist),
    )


SupervisedPortalServiceDependency = Annotated[
    SupervisedPortalService, Depends(get_supervised_portal_service)
]


def get_field_execution_service(
    session: SessionDependency,
    cipher: CipherDependency,
) -> ApplicationFieldExecutionService:
    settings = get_settings()
    knowledge = CandidateKnowledgeRepository(session)
    bindings = ApplicationFieldBindingRepository(session)
    return ApplicationFieldExecutionService(
        bindings=bindings,
        binding_service=ApplicationFieldBindingService(knowledge, bindings, cipher),
        answers=knowledge,
        applications=ApplicationRepository(session),
        executions=ApplicationFieldExecutionRepository(session),
        supervised=SupervisedPortalRepository(session),
        browser=get_browser_service(session, cipher),
        cipher=cipher,
        enabled=settings.supervised_field_execution_enabled,
    )


FieldExecutionServiceDependency = Annotated[
    ApplicationFieldExecutionService, Depends(get_field_execution_service)
]


def get_field_coverage_service(
    session: SessionDependency,
) -> ApplicationFieldCoverageService:
    return ApplicationFieldCoverageService(
        bindings=ApplicationFieldBindingRepository(session),
        answers=CandidateKnowledgeRepository(session),
        applications=ApplicationRepository(session),
        executions=ApplicationFieldExecutionRepository(session),
        supervised=SupervisedPortalRepository(session),
    )


FieldCoverageServiceDependency = Annotated[
    ApplicationFieldCoverageService, Depends(get_field_coverage_service)
]


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, PortalEligibilityError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    if isinstance(error, PortalApprovalError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, SupervisedPortalPolicyError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    if isinstance(error, FieldExecutionPolicyError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    if isinstance(error, BrowserPolicyError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    if isinstance(error, SupervisedPortalStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, FieldExecutionConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, BrowserSessionStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, BrowserWorkerUnavailableError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser worker is unavailable; supervised evidence was preserved",
        )
    if isinstance(error, BrowserWorkerError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    if isinstance(error, (PortalExecutionError, ValueError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    if isinstance(error, FieldExecutionError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    if isinstance(error, IntegrityError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Portal record conflict")
    raise error


@router.get("/catalog", response_model=list[PortalAdapterDefinition])
def list_portal_catalog(catalog: PortalCatalogDependency) -> list[PortalAdapterDefinition]:
    return catalog.definitions()


@router.get("/catalog/{portal}", response_model=PortalAdapterDefinition)
def get_portal_definition(
    portal: PortalKind, catalog: PortalCatalogDependency
) -> PortalAdapterDefinition:
    try:
        return catalog.get(portal)
    except LookupError as error:
        raise _http_error(error) from error


@router.post("/identify", response_model=PortalPageMatch)
def identify_portal_page(
    probe: PortalPageProbe, catalog: PortalCatalogDependency
) -> PortalPageMatch:
    try:
        return catalog.identify(**probe.model_dump())
    except PortalCatalogError as error:
        raise _http_error(error) from error


@router.post("/replays/validate", response_model=list[PortalRegressionMetric])
def validate_portal_replays(
    cases: list[PortalReplayCase], catalog: PortalCatalogDependency
) -> list[PortalRegressionMetric]:
    try:
        return catalog.run_replays(cases)
    except PortalCatalogError as error:
        raise _http_error(error) from error


@router.post(
    "/supervised/runs",
    response_model=SupervisedPortalRunSnapshot,
    status_code=status.HTTP_201_CREATED,
)
def start_supervised_portal_run(
    command: SupervisedPortalRunCreate,
    service: SupervisedPortalServiceDependency,
) -> SupervisedPortalRunSnapshot:
    try:
        return service.start(command)
    except (
        LookupError,
        BrowserPolicyError,
        BrowserSessionStateError,
        BrowserWorkerError,
        SupervisedPortalPolicyError,
        SupervisedPortalStateError,
    ) as error:
        raise _http_error(error) from error


@router.get("/supervised/runs", response_model=list[SupervisedPortalRunSnapshot])
def list_supervised_portal_runs(
    service: SupervisedPortalServiceDependency,
) -> list[SupervisedPortalRunSnapshot]:
    return service.list_runs()


@router.get("/supervised/runs/{run_id}", response_model=SupervisedPortalRunSnapshot)
def get_supervised_portal_run(
    run_id: str, service: SupervisedPortalServiceDependency
) -> SupervisedPortalRunSnapshot:
    try:
        return service.get(run_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.post("/supervised/runs/{run_id}/capture", response_model=SupervisedPortalRunSnapshot)
def capture_supervised_portal_step(
    run_id: str,
    command: SupervisedPortalCapture,
    service: SupervisedPortalServiceDependency,
) -> SupervisedPortalRunSnapshot:
    try:
        return service.capture(run_id, command)
    except (
        LookupError,
        BrowserPolicyError,
        BrowserSessionStateError,
        BrowserWorkerError,
        SupervisedPortalPolicyError,
        SupervisedPortalStateError,
    ) as error:
        raise _http_error(error) from error


@router.post(
    "/supervised/runs/{run_id}/field-executions",
    response_model=ApplicationFieldExecution,
    status_code=status.HTTP_201_CREATED,
)
def execute_approved_application_field(
    run_id: str,
    approval: ApplicationFieldExecutionApproval,
    service: FieldExecutionServiceDependency,
) -> ApplicationFieldExecution:
    try:
        return service.execute(run_id, approval)
    except (
        LookupError,
        BrowserPolicyError,
        BrowserSessionStateError,
        BrowserWorkerError,
        FieldExecutionError,
    ) as error:
        raise _http_error(error) from error


@router.get(
    "/supervised/runs/{run_id}/applications/{application_id}/field-coverage",
    response_model=ApplicationFieldCoverageReview,
)
def review_required_field_coverage(
    run_id: str,
    application_id: str,
    service: FieldCoverageServiceDependency,
) -> ApplicationFieldCoverageReview:
    try:
        return service.review(run_id, application_id)
    except (LookupError, ValueError) as error:
        raise _http_error(error) from error


@router.get(
    "/supervised/applications/{application_id}/field-executions",
    response_model=list[ApplicationFieldExecution],
)
def list_application_field_executions(
    application_id: str,
    service: FieldExecutionServiceDependency,
) -> list[ApplicationFieldExecution]:
    return service.list_for_application(application_id)


@router.post("/supervised/runs/{run_id}/submit", response_model=SupervisedPortalRunSnapshot)
def submit_supervised_portal_run(
    run_id: str,
    approval: SupervisedPortalSubmissionApproval,
    service: SupervisedPortalServiceDependency,
) -> SupervisedPortalRunSnapshot:
    try:
        return service.submit(run_id, approval)
    except (
        LookupError,
        BrowserPolicyError,
        BrowserSessionStateError,
        BrowserWorkerError,
        SupervisedPortalPolicyError,
        SupervisedPortalStateError,
    ) as error:
        raise _http_error(error) from error


@router.post("/supervised/runs/{run_id}/stop", response_model=SupervisedPortalRunSnapshot)
def stop_supervised_portal_run(
    run_id: str, service: SupervisedPortalServiceDependency
) -> SupervisedPortalRunSnapshot:
    try:
        return service.stop(run_id)
    except (
        LookupError,
        BrowserSessionStateError,
        BrowserWorkerError,
        SupervisedPortalStateError,
    ) as error:
        raise _http_error(error) from error


@router.post(
    "/reference/runs",
    response_model=PortalRunSnapshot,
    status_code=status.HTTP_201_CREATED,
)
def prepare_reference_run(
    command: ReferencePortalRunCreate,
    service: PortalServiceDependency,
) -> PortalRunSnapshot:
    try:
        return service.prepare(command)
    except (LookupError, PortalExecutionError, ValueError, IntegrityError) as error:
        raise _http_error(error) from error


@router.get("/runs", response_model=list[PortalRunSnapshot])
def list_portal_runs(service: PortalServiceDependency) -> list[PortalRunSnapshot]:
    return service.list_runs()


@router.get("/runs/{run_id}", response_model=PortalRunSnapshot)
def get_portal_run(run_id: str, service: PortalServiceDependency) -> PortalRunSnapshot:
    try:
        return service.get(run_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.post("/runs/{run_id}/confirm", response_model=PortalRunSnapshot)
def confirm_portal_run(
    run_id: str,
    approval: SubmissionApproval,
    service: PortalServiceDependency,
) -> PortalRunSnapshot:
    try:
        return service.confirm(run_id, approval)
    except (LookupError, PortalExecutionError, ValueError) as error:
        raise _http_error(error) from error
