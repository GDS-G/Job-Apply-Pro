from __future__ import annotations

import json
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.ai.prompts import AGENT_SCHEMAS
from job_apply_pro.ai.providers import (
    AIProviderError,
    AIProviderRuntime,
    OpenAICompatibleProvider,
)
from job_apply_pro.ai.registry import AIRegistry
from job_apply_pro.api.routes.ai import get_ai_gateway
from job_apply_pro.domain.ai import (
    AgentRole,
    AgentRunRequest,
    AICapability,
    AIGatewayRequest,
    AIInputPart,
    AIModelDefinition,
    AIProviderDefinition,
    AIProviderRequest,
    AIProviderResponse,
    AIRoutingPolicy,
    AITaskType,
    AIToolDefinition,
    DataClassification,
    EvaluationCase,
    ProviderKind,
)
from job_apply_pro.main import app
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.ai import (
    AgentService,
    AIEvaluationHarness,
    AIGatewayPolicyError,
    AIGatewayService,
    AIGatewayUnavailableError,
)
from job_apply_pro.storage.ai_repository import AIGatewayRepository
from job_apply_pro.storage.models import AICacheRow, ModelInvocationRow


class FakeProvider:
    def __init__(
        self,
        provider_id: str,
        responses: list[str | Exception],
        *,
        external: bool = False,
    ) -> None:
        self.definition = AIProviderDefinition.model_validate(
            {
                "id": provider_id,
                "kind": (ProviderKind.OPENAI_COMPATIBLE if external else ProviderKind.LLAMA_CPP),
                "base_url": (
                    "https://models.example.test/v1" if external else "http://127.0.0.1:8080/v1"
                ),
                "external": external,
            }
        )
        self.responses = iter(responses)
        self.requests: list[AIProviderRequest] = []

    def complete(self, request: AIProviderRequest) -> AIProviderResponse:
        self.requests.append(request)
        try:
            response = next(self.responses)
        except StopIteration as error:
            raise AIProviderError("fixture response exhausted") from error
        if isinstance(response, Exception):
            raise response
        return AIProviderResponse(content=response, input_tokens=100, output_tokens=25)

    def embed(self, model: str, texts: list[str], timeout_seconds: float) -> list[list[float]]:
        return [[float(index), 1.0] for index, _ in enumerate(texts)]


def _models(*provider_ids: str, cost: int = 0) -> list[AIModelDefinition]:
    return [
        AIModelDefinition(
            id=f"{provider_id}.answer",
            provider_id=provider_id,
            model="fixture-model",
            capabilities={AICapability.TEXT, AICapability.STRUCTURED_OUTPUT},
            context_window=8_192,
            input_cost_micros_per_million=cost,
            output_cost_micros_per_million=cost,
        )
        for provider_id in provider_ids
    ]


def _policy(*model_ids: str, retries: int = 0, allow_external: bool = True) -> AIRoutingPolicy:
    return AIRoutingPolicy(
        task_type=AITaskType.ANSWER,
        model_order=list(model_ids),
        required_capabilities={AICapability.TEXT, AICapability.STRUCTURED_OUTPUT},
        allow_external=allow_external,
        max_cost_micros=1_000,
        retries_per_model=retries,
        cache_ttl_seconds=3_600,
    )


def _request(**changes: object) -> AIGatewayRequest:
    values: dict[str, object] = {
        "task_type": AITaskType.ANSWER,
        "prompt_id": "agent.answer",
        "input_data": {"question": "Why are you qualified?", "evidence": ["claim-1"]},
        "output_schema": AGENT_SCHEMAS[AgentRole.ANSWER],
        "profile_id": "profile-1",
        "source_version": "resume-v1",
    }
    values.update(changes)
    return AIGatewayRequest.model_validate(values)


def _service(
    session: Session,
    providers: list[FakeProvider],
    models: list[AIModelDefinition],
    policies: list[AIRoutingPolicy],
) -> AIGatewayService:
    return AIGatewayService(
        AIRegistry(providers, models, policies),
        AIGatewayRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"a" * 32)),
    )


def test_structured_output_falls_back_and_records_encrypted_cache(session: Session) -> None:
    primary = FakeProvider("primary", [AIProviderError("offline")])
    fallback = FakeProvider(
        "fallback",
        [
            json.dumps(
                {
                    "answer": "Evidence-backed answer",
                    "evidence_claim_ids": ["claim-1"],
                    "needs_user": False,
                }
            )
        ],
    )
    models = _models("primary", "fallback")
    service = _service(
        session,
        [primary, fallback],
        models,
        [_policy(*(model.id for model in models))],
    )

    response = service.invoke(_request())
    assert response.provider_id == "fallback"
    assert response.attempts == 2
    assert response.schema_valid is True
    assert cast(dict[str, object], response.content)["answer"] == "Evidence-backed answer"

    cache = session.scalar(select(AICacheRow))
    assert cache is not None
    assert "Evidence-backed answer" not in cache.encrypted_response
    invocation = session.scalar(select(ModelInvocationRow))
    assert invocation is not None
    assert invocation.input_hash and invocation.route_json == ["primary.answer", "fallback.answer"]


def test_cache_reuse_avoids_second_provider_call(session: Session) -> None:
    provider = FakeProvider(
        "local",
        [json.dumps({"answer": "Cached", "evidence_claim_ids": [], "needs_user": False})],
    )
    models = _models("local")
    service = _service(session, [provider], models, [_policy(models[0].id)])
    first = service.invoke(_request())
    second = service.invoke(_request())

    assert first.cached is False
    assert second.cached is True
    assert second.invocation_id != first.invocation_id
    assert len(provider.requests) == 1
    assert len(session.scalars(select(ModelInvocationRow)).all()) == 2


def test_external_privacy_requires_consent_blocks_restricted_and_redacts(
    session: Session,
) -> None:
    provider = FakeProvider(
        "cloud",
        [json.dumps({"answer": "Safe", "evidence_claim_ids": [], "needs_user": False})],
        external=True,
    )
    models = _models("cloud")
    service = _service(session, [provider], models, [_policy(models[0].id)])

    with pytest.raises(AIGatewayPolicyError, match="consent"):
        service.invoke(_request(input_data={"email": "candidate@example.com"}))
    with pytest.raises(AIGatewayPolicyError, match="blocked"):
        service.invoke(
            _request(
                classification=DataClassification.RESTRICTED,
                external_consent=True,
            )
        )

    service.invoke(_request(input_data={"email": "candidate@example.com"}, external_consent=True))
    assert "candidate@example.com" not in provider.requests[0].user_content
    assert "[EMAIL_REDACTED]" in provider.requests[0].user_content


def test_invalid_structured_output_is_retried_then_rejected(session: Session) -> None:
    provider = FakeProvider("local", ["not-json", '{"answer":"missing required keys"}'])
    models = _models("local")
    service = _service(session, [provider], models, [_policy(models[0].id, retries=1)])

    with pytest.raises(AIGatewayUnavailableError):
        service.invoke(_request())
    assert len(provider.requests) == 2
    assert "corrected JSON" in provider.requests[1].system_instruction
    invocation = session.scalar(select(ModelInvocationRow))
    assert invocation is not None and invocation.status == "FAILED" and invocation.attempts == 2


def test_agent_evaluation_harness_uses_schema_valid_results(session: Session) -> None:
    provider = FakeProvider(
        "local",
        [
            json.dumps(
                {"answer": "Reviewed", "evidence_claim_ids": ["claim-1"], "needs_user": False}
            )
        ],
    )
    models = _models("local")
    service = _service(session, [provider], models, [_policy(models[0].id)])
    harness = AIEvaluationHarness(AgentService(service))
    report = harness.run(
        [
            EvaluationCase(
                id="answer-grounding",
                agent_request=AgentRunRequest(
                    role=AgentRole.ANSWER,
                    input_data={"question": "Why?", "evidence_claim_ids": ["claim-1"]},
                ),
                required_keys={"answer", "evidence_claim_ids", "needs_user"},
                expected_values={"needs_user": False},
            )
        ]
    )
    assert report.total == report.passed == 1
    assert report.failed == 0


def test_openai_compatible_adapter_supports_chat_and_embeddings() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [0.25, 0.75]}]},
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"valid":true}',
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "classify_page",
                                        "arguments": '{"kind":"application"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    provider = OpenAICompatibleProvider(
        AIProviderRuntime.model_validate(
            {
                "definition": {
                    "id": "cloud",
                    "kind": ProviderKind.SECONDARY_COMPATIBLE,
                    "base_url": "https://models.example.test/v1",
                    "external": True,
                },
                "api_key": "test-secret",
            }
        ),
        transport=httpx.MockTransport(handler),
    )
    result = provider.complete(
        AIProviderRequest(
            model="fixture",
            system_instruction="Return JSON",
            user_content="data",
            input_parts=[
                AIInputPart(kind="image_url", value="https://images.example.test/page.png")
            ],
            tools=[
                AIToolDefinition(
                    name="classify_page",
                    description="Classify a minimized portal page observation",
                    input_schema={"type": "object"},
                )
            ],
            output_schema={"type": "object"},
            timeout_seconds=5,
        )
    )
    vectors = provider.embed("embedding-fixture", ["text"], 5)

    assert result.content == '{"valid":true}'
    assert result.input_tokens == 4 and result.output_tokens == 2
    assert result.tool_calls[0].name == "classify_page"
    assert vectors == [[0.25, 0.75]]
    assert requests[0].headers["authorization"] == "Bearer test-secret"
    assert "json_schema" in requests[0].read().decode()
    assert "image_url" in requests[0].read().decode()
    assert "classify_page" in requests[0].read().decode()


def test_external_adapter_requires_https_and_local_requires_loopback() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAICompatibleProvider(
            AIProviderRuntime.model_validate(
                {
                    "definition": {
                        "id": "bad-cloud",
                        "kind": ProviderKind.OPENAI_COMPATIBLE,
                        "base_url": "http://models.example.test/v1",
                        "external": True,
                    }
                }
            )
        )
    with pytest.raises(ValueError, match="loopback"):
        OpenAICompatibleProvider(
            AIProviderRuntime.model_validate(
                {
                    "definition": {
                        "id": "bad-local",
                        "kind": ProviderKind.LLAMA_CPP,
                        "base_url": "http://192.168.1.20:8080/v1",
                        "external": False,
                    }
                }
            )
        )


def test_authenticated_ai_api_exposes_status_and_bounded_agent(
    session: Session,
) -> None:
    provider = FakeProvider(
        "local",
        [json.dumps({"answer": "API answer", "evidence_claim_ids": [], "needs_user": False})],
    )
    models = _models("local")
    service = _service(session, [provider], models, [_policy(models[0].id)])
    app.dependency_overrides[get_ai_gateway] = lambda: service
    try:
        client = TestClient(app)
        status_response = client.get("/api/v1/ai/status")
        agent_response = client.post(
            "/api/v1/ai/agents/run",
            json={
                "role": "ANSWER",
                "input_data": {"question": "Why?", "evidence_claim_ids": []},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert status_response.status_code == 200
    assert status_response.json()["provider_count"] == 1
    assert agent_response.status_code == 200
    assert agent_response.json()["output"]["answer"] == "API answer"
