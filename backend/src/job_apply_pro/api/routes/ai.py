from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
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
from job_apply_pro.storage.ai_repository import AIGatewayRepository
from job_apply_pro.storage.database import get_session

router = APIRouter(prefix="/ai", tags=["ai-gateway"])
SessionDependency = Annotated[Session, Depends(get_session)]
CipherDependency = Annotated[SensitiveDataCipher, Depends(get_cipher)]


def get_ai_gateway(session: SessionDependency, cipher: CipherDependency) -> AIGatewayService:
    return AIGatewayService(
        build_ai_registry(get_settings().ai_config_json), AIGatewayRepository(session), cipher
    )


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
