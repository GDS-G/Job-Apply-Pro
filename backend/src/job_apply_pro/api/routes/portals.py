from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.browser import get_browser_service
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
)
from job_apply_pro.portals.catalog import PortalCatalog, PortalCatalogError
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.services.core import CoreService
from job_apply_pro.services.portals import (
    PortalApprovalError,
    PortalEligibilityError,
    PortalExecutionError,
    ReferencePortalService,
)
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    CheckpointRepository,
    JobRepository,
    PortalRunRepository,
    WorkbenchRepository,
)

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
    )


PortalServiceDependency = Annotated[ReferencePortalService, Depends(get_portal_service)]


def get_portal_catalog() -> PortalCatalog:
    return PortalCatalog()


PortalCatalogDependency = Annotated[PortalCatalog, Depends(get_portal_catalog)]


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, PortalEligibilityError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    if isinstance(error, PortalApprovalError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, (PortalExecutionError, ValueError)):
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
