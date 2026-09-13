from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from job_apply_pro.domain.job_discovery import (
    GreenhouseBoardRequest,
    GreenhouseImportRequest,
    GreenhouseImportResult,
    GreenhouseJobList,
    GreenhouseJobReview,
    GreenhouseReviewRequest,
)
from job_apply_pro.portals.greenhouse import GreenhouseDiscoveryError, GreenhousePublicBoardClient
from job_apply_pro.services.job_discovery import GreenhouseDiscoveryService
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.job_discovery_repository import (
    GreenhouseDiscoveryRepository,
    GreenhouseImportConflictError,
)

router = APIRouter(prefix="/discovery/greenhouse", tags=["public-discovery"])


def get_public_board_client() -> GreenhousePublicBoardClient:
    return GreenhousePublicBoardClient()


PublicClient = Annotated[GreenhousePublicBoardClient, Depends(get_public_board_client)]
SessionDependency = Annotated[Session, Depends(get_session)]


@router.post("/list", response_model=GreenhouseJobList)
def list_jobs(command: GreenhouseBoardRequest, client: PublicClient) -> GreenhouseJobList:
    try:
        return client.list_jobs(command)
    except GreenhouseDiscoveryError:
        raise HTTPException(
            502, "Public job discovery was unavailable or outside supported limits"
        ) from None


@router.post("/review", response_model=GreenhouseJobReview)
def review_job(command: GreenhouseReviewRequest, client: PublicClient) -> GreenhouseJobReview:
    try:
        return client.review_job(command)
    except GreenhouseDiscoveryError:
        raise HTTPException(
            502, "Public job review was unavailable or outside supported limits"
        ) from None


@router.post("/import", response_model=GreenhouseImportResult)
def import_job(
    command: GreenhouseImportRequest,
    client: PublicClient,
    session: SessionDependency,
) -> GreenhouseImportResult:
    try:
        return GreenhouseDiscoveryService(
            GreenhouseDiscoveryRepository(session), client
        ).import_job(command)
    except GreenhouseDiscoveryError:
        raise HTTPException(
            502, "Public job import was unavailable or outside supported limits"
        ) from None
    except GreenhouseImportConflictError:
        raise HTTPException(
            409, "Local import conflicted; select an existing profile and refresh"
        ) from None
