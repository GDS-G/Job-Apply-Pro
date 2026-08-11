from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.browser import get_browser_service
from job_apply_pro.challenges.answer_mapping import ChallengeAnswerMapper
from job_apply_pro.domain.challenges import (
    ChallengeAnswerCommand,
    ChallengeAnswerSuggestion,
    ChallengeCompletionCommand,
    ChallengeEvent,
    ChallengeModelRoute,
    ChallengeSessionCreate,
    ChallengeSessionSnapshot,
    InterventionCompleteCommand,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.services.challenges import (
    ChallengeInterventionRequiredError,
    ChallengeService,
    ChallengeServiceError,
)
from job_apply_pro.storage.challenge_repository import ChallengeRepository
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.repositories import CandidateRepository, WorkbenchRepository

from .core import get_cipher

router = APIRouter(prefix="/challenges", tags=["challenges"])
SessionDependency = Annotated[Session, Depends(get_session)]
CipherDependency = Annotated[SensitiveDataCipher, Depends(get_cipher)]


def get_challenge_service(session: SessionDependency, cipher: CipherDependency) -> ChallengeService:
    return ChallengeService(
        ChallengeRepository(session),
        WorkbenchRepository(session),
        get_browser_service(session, cipher),
        answer_mapper=ChallengeAnswerMapper(
            CandidateRepository(session), CandidateKnowledgeRepository(session), cipher
        ),
    )


ChallengeServiceDependency = Annotated[ChallengeService, Depends(get_challenge_service)]


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ChallengeInterventionRequiredError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, (ChallengeServiceError, ValueError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    raise error


@router.post("/detect", response_model=ChallengeSessionSnapshot, status_code=201)
def detect_challenge(
    command: ChallengeSessionCreate, service: ChallengeServiceDependency
) -> ChallengeSessionSnapshot:
    try:
        return service.detect(command)
    except (LookupError, ChallengeServiceError, ValueError) as error:
        raise _http_error(error) from error


@router.get("/sessions", response_model=list[ChallengeSessionSnapshot])
def list_challenge_sessions(
    service: ChallengeServiceDependency,
    workflow_id: Annotated[str | None, Query(max_length=100)] = None,
) -> list[ChallengeSessionSnapshot]:
    return service.list_sessions(workflow_id)


@router.get("/sessions/{session_id}", response_model=ChallengeSessionSnapshot)
def get_challenge_session(
    session_id: str, service: ChallengeServiceDependency
) -> ChallengeSessionSnapshot:
    try:
        return service.get(session_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.get("/sessions/{session_id}/events", response_model=list[ChallengeEvent])
def list_challenge_events(
    session_id: str, service: ChallengeServiceDependency
) -> list[ChallengeEvent]:
    try:
        return service.events(session_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.get(
    "/sessions/{session_id}/suggestions",
    response_model=list[ChallengeAnswerSuggestion],
)
def list_challenge_suggestions(
    session_id: str, service: ChallengeServiceDependency
) -> list[ChallengeAnswerSuggestion]:
    try:
        return service.suggestions(session_id)
    except (LookupError, ChallengeServiceError) as error:
        raise _http_error(error) from error


@router.get(
    "/sessions/{session_id}/model-routes",
    response_model=list[ChallengeModelRoute],
)
def list_challenge_model_routes(
    session_id: str, service: ChallengeServiceDependency
) -> list[ChallengeModelRoute]:
    try:
        return service.model_routes(session_id)
    except (LookupError, ChallengeServiceError) as error:
        raise _http_error(error) from error


@router.post("/sessions/{session_id}/refresh", response_model=ChallengeSessionSnapshot)
def refresh_challenge_session(
    session_id: str, service: ChallengeServiceDependency
) -> ChallengeSessionSnapshot:
    try:
        return service.refresh(session_id)
    except (LookupError, ChallengeServiceError, ValueError) as error:
        raise _http_error(error) from error


@router.post("/sessions/{session_id}/answers", response_model=ChallengeSessionSnapshot)
def answer_challenge(
    session_id: str,
    command: ChallengeAnswerCommand,
    service: ChallengeServiceDependency,
) -> ChallengeSessionSnapshot:
    try:
        return service.answer(session_id, command)
    except (LookupError, ChallengeServiceError, ValueError) as error:
        raise _http_error(error) from error


@router.post("/sessions/{session_id}/complete", response_model=ChallengeSessionSnapshot)
def complete_challenge(
    session_id: str,
    command: ChallengeCompletionCommand,
    service: ChallengeServiceDependency,
) -> ChallengeSessionSnapshot:
    try:
        return service.complete(session_id, command)
    except (LookupError, ChallengeServiceError, ValueError) as error:
        raise _http_error(error) from error


@router.post(
    "/sessions/{session_id}/intervention-complete",
    response_model=ChallengeSessionSnapshot,
)
def complete_intervention(
    session_id: str,
    command: InterventionCompleteCommand,
    service: ChallengeServiceDependency,
) -> ChallengeSessionSnapshot:
    try:
        return service.intervention_complete(session_id, command)
    except (LookupError, ChallengeServiceError, ValueError) as error:
        raise _http_error(error) from error
