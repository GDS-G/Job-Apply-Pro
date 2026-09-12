from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy.orm import Session

from job_apply_pro.ai.configuration import build_ai_registry
from job_apply_pro.api.routes.core import get_cipher
from job_apply_pro.config import get_settings
from job_apply_pro.domain.ai import (
    AgentRunRequest,
    AgentRunResult,
    AIEmbeddingRequest,
    AIEmbeddingResponse,
    AIGatewayRequest,
    AIGatewayResponse,
    AIRerankRequest,
    AIRerankResult,
    EvaluationCase,
    EvaluationReport,
)
from job_apply_pro.domain.media_cleanup import MediaCleanupPublicRecord
from job_apply_pro.security.encryption import DecryptionError, SensitiveDataCipher
from job_apply_pro.security.keys import KeyConfigurationError
from job_apply_pro.services.ai import (
    AgentService,
    AIEvaluationHarness,
    AIGatewayError,
    AIGatewayPolicyError,
    AIGatewayService,
    AIGatewayUnavailableError,
    AIGatewayValidationError,
)
from job_apply_pro.services.media_cleanup import MediaCleanupService
from job_apply_pro.storage.ai_repository import AIGatewayRepository
from job_apply_pro.storage.database import SessionFactory, get_session
from job_apply_pro.storage.media_cleanup_repository import (
    MediaCleanupConflict,
    MediaCleanupRepository,
)

router = APIRouter(prefix="/ai", tags=["ai-gateway"])
SessionDependency = Annotated[Session, Depends(get_session)]
CipherDependency = Annotated[SensitiveDataCipher, Depends(get_cipher)]


def get_ai_gateway(session: SessionDependency, cipher: CipherDependency) -> AIGatewayService:
    return AIGatewayService(
        build_ai_registry(
            get_settings().ai_config_json,
            journal_factory=get_media_cleanup_service(cipher).journal_factory,
        ),
        AIGatewayRepository(session),
        cipher,
    )


def get_media_cleanup_service(cipher: CipherDependency) -> MediaCleanupService:
    return MediaCleanupService(
        MediaCleanupRepository(SessionFactory, cipher), cipher, get_settings().ai_config_json
    )


CleanupDependency = Annotated[MediaCleanupService, Depends(get_media_cleanup_service)]


class MediaCleanupListResponse(BaseModel):
    items: list[MediaCleanupPublicRecord]


class MediaCleanupResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: AwareDatetime
    confirmation: Literal["I VERIFIED PROVIDER MEDIA CLEANUP"]


@router.get("/media-cleanup", response_model=MediaCleanupListResponse)
def list_media_cleanup(service: CleanupDependency) -> MediaCleanupListResponse:
    return MediaCleanupListResponse(items=service.list_public())


@router.post("/media-cleanup/retry", response_model=MediaCleanupListResponse)
def retry_media_cleanup(service: CleanupDependency) -> MediaCleanupListResponse:
    try:
        service.recover()
    except Exception as error:
        raise HTTPException(
            503, "Media cleanup could not run; unresolved records are retained"
        ) from error
    return MediaCleanupListResponse(items=service.list_public())


@router.post("/media-cleanup/{record_id}/resolve", response_model=MediaCleanupListResponse)
def resolve_media_cleanup(
    record_id: UUID, command: MediaCleanupResolution, service: CleanupDependency
) -> MediaCleanupListResponse:
    try:
        service.resolve_manual(str(record_id), command.expected_updated_at)
    except MediaCleanupConflict as error:
        raise HTTPException(
            409, "Media cleanup review changed or cannot be acknowledged"
        ) from error
    return MediaCleanupListResponse(items=service.list_public())


GatewayDependency = Annotated[AIGatewayService, Depends(get_ai_gateway)]


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, AIGatewayPolicyError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    if isinstance(error, AIGatewayValidationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    if isinstance(error, AIGatewayUnavailableError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    if isinstance(error, (KeyConfigurationError, DecryptionError)):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI cache encryption is unavailable",
        )
    raise error


@router.get("/status")
def ai_status(service: GatewayDependency) -> dict[str, object]:
    providers = service.providers()
    models = service.models()
    return {
        "status": "ready" if providers and models else "not_configured",
        "provider_count": len(providers),
        "model_count": len(models),
        "external_calls_require_consent": True,
        "restricted_external_data_blocked": True,
    }


@router.get("/providers")
def list_ai_providers(service: GatewayDependency) -> list[object]:
    return service.providers()


@router.get("/models")
def list_ai_models(service: GatewayDependency) -> list[object]:
    return service.models()


@router.post("/invoke", response_model=AIGatewayResponse)
def invoke_ai(command: AIGatewayRequest, service: GatewayDependency) -> AIGatewayResponse:
    try:
        return service.invoke(command)
    except (AIGatewayError, KeyConfigurationError, DecryptionError) as error:
        raise _http_error(error) from error


@router.post("/embed", response_model=AIEmbeddingResponse)
def embed_text(command: AIEmbeddingRequest, service: GatewayDependency) -> AIEmbeddingResponse:
    try:
        return service.embed(command)
    except (AIGatewayError, KeyConfigurationError, DecryptionError) as error:
        raise _http_error(error) from error


@router.post("/rerank", response_model=list[AIRerankResult])
def rerank(command: AIRerankRequest, service: GatewayDependency) -> list[AIRerankResult]:
    try:
        return service.rerank(command)
    except (AIGatewayError, KeyConfigurationError, DecryptionError) as error:
        raise _http_error(error) from error


@router.post("/agents/run", response_model=AgentRunResult)
def run_agent(command: AgentRunRequest, service: GatewayDependency) -> AgentRunResult:
    try:
        return AgentService(service).run(command)
    except (AIGatewayError, KeyConfigurationError, DecryptionError) as error:
        raise _http_error(error) from error


@router.post("/evaluations/run", response_model=EvaluationReport)
def run_evaluations(cases: list[EvaluationCase], service: GatewayDependency) -> EvaluationReport:
    try:
        return AIEvaluationHarness(AgentService(service)).run(cases)
    except (AIGatewayError, KeyConfigurationError, DecryptionError) as error:
        raise _http_error(error) from error
