from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from typing import TypeVar, cast
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError

from job_apply_pro.ai.prompts import (
    AGENT_SCHEMAS,
    AGENT_TASKS,
    default_prompt_registry,
    redact_external_data,
    render_prompt,
)
from job_apply_pro.ai.providers import AIProviderError
from job_apply_pro.ai.registry import AIRegistry
from job_apply_pro.domain.ai import (
    AgentRunRequest,
    AgentRunResult,
    AICacheRecord,
    AIEmbeddingRequest,
    AIEmbeddingResponse,
    AIGatewayRequest,
    AIGatewayResponse,
    AIInputPart,
    AIInvocationRecord,
    AIModelDefinition,
    AIProviderRequest,
    AIRerankRequest,
    AIRerankResult,
    AITaskType,
    AIToolCall,
    AIUsage,
    DataClassification,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationReport,
    PromptTemplate,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.storage.repository_contracts import AIGatewayRepositoryProtocol


class AIGatewayError(RuntimeError):
    pass


class AIGatewayPolicyError(AIGatewayError):
    pass


class AIGatewayValidationError(AIGatewayError):
    pass


class AIGatewayUnavailableError(AIGatewayError):
    pass


AuthorizedInput = TypeVar("AuthorizedInput")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class AIGatewayService:
    def __init__(
        self,
        registry: AIRegistry,
        repository: AIGatewayRepositoryProtocol,
        cipher: SensitiveDataCipher,
        prompts: dict[str, PromptTemplate] | None = None,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._cipher = cipher
        self._prompts = prompts or default_prompt_registry()

    def providers(self) -> list[object]:
        return [item.model_dump(mode="json") for item in self._registry.provider_definitions()]

    def models(self) -> list[object]:
        return [item.model_dump(mode="json") for item in self._registry.model_definitions()]

    def invoke(self, request: AIGatewayRequest) -> AIGatewayResponse:
        prompt = self._prompt(request)
        self._validate_request_tools(request, prompt)
        routes = self._registry.routes(request.task_type)
        route_ids = [model.id for _, model in routes]
        started_at = datetime.now(UTC)
        started_clock = time.monotonic()
        input_hash = self._hash(request.input_data)
        attempts = 0
        last_error: Exception | None = None
        last_provider = routes[-1][0].definition.id
        last_model = routes[-1][1].id

        for provider, model in routes:
            last_provider, last_model = provider.definition.id, model.id
            cache_key = self._cache_key(request, prompt, model.id)
            if request.cache_mode == "USE":
                cached = self._read_cache(cache_key)
                if cached is not None:
                    response = cached.model_copy(
                        update={"invocation_id": str(uuid4()), "cached": True, "attempts": 0}
                    )
                    self._record(
                        response,
                        request,
                        input_hash,
                        cache_key,
                        route_ids,
                        started_at,
                        started_clock,
                        status="CACHED",
                    )
                    return response

            prepared_input = self._authorize_input(
                request.input_data,
                request.classification,
                request.external_consent,
                provider.definition.external,
            )
            prepared_parts = self._authorized_parts(
                request.input_parts,
                request.classification,
                request.external_consent,
                provider.definition.external,
            )
            system, user = render_prompt(prompt, prepared_input)
            policy = self._registry.policy(request.task_type)
            timeout = min(request.timeout_seconds or policy.timeout_seconds, policy.timeout_seconds)
            for attempt in range(policy.retries_per_model + 1):
                attempts += 1
                try:
                    repair = (
                        "\nPrevious output failed schema validation. Return only corrected JSON."
                        if attempt
                        else ""
                    )
                    raw = provider.complete(
                        AIProviderRequest(
                            model=model.model,
                            system_instruction=system + repair,
                            user_content=user,
                            input_parts=prepared_parts,
                            tools=request.tools,
                            output_schema=request.output_schema,
                            timeout_seconds=timeout,
                        )
                    )
                    content = self._validated_content(raw.content, request.output_schema)
                    tool_calls = self._validated_tool_calls(raw.tool_calls, request)
                    cost = self._cost(model, raw.input_tokens, raw.output_tokens)
                    budget = (
                        min(request.max_cost_micros, policy.max_cost_micros)
                        if request.max_cost_micros is not None
                        else policy.max_cost_micros
                    )
                    if cost > budget:
                        raise AIGatewayPolicyError(
                            f"Model response cost {cost} exceeds the {budget}-micro budget"
                        )
                    response = AIGatewayResponse(
                        invocation_id=str(uuid4()),
                        task_type=request.task_type,
                        provider_id=provider.definition.id,
                        model_id=model.id,
                        content=content,
                        tool_calls=tool_calls,
                        usage=AIUsage(
                            input_tokens=raw.input_tokens,
                            output_tokens=raw.output_tokens,
                            cost_micros=cost,
                        ),
                        attempts=attempts,
                        schema_valid=True,
                        prompt_version=prompt.version,
                        schema_version=prompt.schema_version,
                        classification=request.classification,
                        created_at=datetime.now(UTC),
                    )
                    self._record(
                        response,
                        request,
                        input_hash,
                        cache_key,
                        route_ids,
                        started_at,
                        started_clock,
                        status="SUCCEEDED",
                    )
                    if request.cache_mode != "BYPASS" and policy.cache_ttl_seconds:
                        self._write_cache(response, request, cache_key, policy.cache_ttl_seconds)
                    return response
                except (AIProviderError, AIGatewayValidationError, AIGatewayPolicyError) as error:
                    last_error = error

        failed = AIGatewayResponse(
            invocation_id=str(uuid4()),
            task_type=request.task_type,
            provider_id=last_provider,
            model_id=last_model,
            content="",
            tool_calls=[],
            usage=AIUsage(),
            attempts=attempts,
            schema_valid=False,
            prompt_version=prompt.version,
            schema_version=prompt.schema_version,
            classification=request.classification,
            created_at=datetime.now(UTC),
        )
        self._record(
            failed,
            request,
            input_hash,
            self._cache_key(request, prompt, last_model),
            route_ids,
            started_at,
            started_clock,
            status="FAILED",
            error_code=type(last_error).__name__ if last_error else "NO_ROUTE",
        )
        if isinstance(last_error, AIGatewayPolicyError):
            raise last_error
        raise AIGatewayUnavailableError("Every configured AI route failed safely") from last_error

    def embed(self, request: AIEmbeddingRequest) -> AIEmbeddingResponse:
        for provider, model in self._registry.embedding_routes():
            try:
                texts = self._authorize_input(
                    request.texts,
                    request.classification,
                    request.external_consent,
                    provider.definition.external,
                )
                vectors = provider.embed(model.model, list(texts), 30)
                return AIEmbeddingResponse(
                    provider_id=provider.definition.id,
                    model_id=model.id,
                    vectors=vectors,
                    usage=AIUsage(),
                )
            except (AIProviderError, AIGatewayPolicyError):
                continue
        raise AIGatewayUnavailableError("Every configured embedding route failed safely")

    def rerank(self, request: AIRerankRequest) -> list[AIRerankResult]:
        schema: dict[str, object] = {
            "type": "object",
            "required": ["results"],
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["index", "score"],
                        "properties": {
                            "index": {"type": "integer", "minimum": 0},
                            "score": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "additionalProperties": False,
                    },
                }
            },
            "additionalProperties": False,
        }
        response = self.invoke(
            AIGatewayRequest(
                task_type=AITaskType.RERANKING,
                prompt_id="gateway.rerank",
                input_data={"query": request.query, "documents": request.documents},
                output_schema=schema,
                profile_id=request.profile_id,
                classification=request.classification,
                external_consent=request.external_consent,
            )
        )
        if not isinstance(response.content, dict):
            raise AIGatewayValidationError("Reranker returned non-object content")
        items = cast(list[object], response.content["results"])
        results = [AIRerankResult.model_validate(item) for item in items]
        return sorted(results, key=lambda item: (-item.score, item.index))[: request.limit]

    def _prompt(self, request: AIGatewayRequest) -> PromptTemplate:
        prompt = self._prompts.get(request.prompt_id)
        if prompt is None or prompt.task_type is not request.task_type:
            raise AIGatewayValidationError("Prompt is missing or does not match the task type")
        if request.output_schema is not None:
            try:
                Draft202012Validator.check_schema(request.output_schema)
            except Exception as error:
                raise AIGatewayValidationError("Output schema is invalid") from error
        return prompt

    @staticmethod
    def _validate_request_tools(request: AIGatewayRequest, prompt: PromptTemplate) -> None:
        allowed = set(prompt.allowed_tools)
        if any(tool.name not in allowed for tool in request.tools):
            raise AIGatewayPolicyError("Request includes a tool not allowed by the prompt")
        for tool in request.tools:
            try:
                Draft202012Validator.check_schema(tool.input_schema)
            except Exception as error:
                raise AIGatewayValidationError(
                    f"Tool {tool.name} has an invalid input schema"
                ) from error

    @staticmethod
    def _validated_tool_calls(
        calls: list[AIToolCall], request: AIGatewayRequest
    ) -> list[AIToolCall]:
        definitions = {tool.name: tool for tool in request.tools}
        for call in calls:
            definition = definitions.get(call.name)
            if definition is None:
                raise AIGatewayValidationError("Model requested an undeclared tool")
            try:
                Draft202012Validator(definition.input_schema).validate(call.arguments)
            except ValidationError as error:
                raise AIGatewayValidationError("Model tool arguments failed validation") from error
        return calls

    @staticmethod
    def _authorize_input(
        value: AuthorizedInput,
        classification: DataClassification,
        external_consent: bool,
        external: bool,
    ) -> AuthorizedInput:
        if not external:
            return value
        if not external_consent:
            raise AIGatewayPolicyError("External AI use requires explicit user consent")
        if classification in {DataClassification.HIGHLY_SENSITIVE, DataClassification.RESTRICTED}:
            raise AIGatewayPolicyError(
                f"{classification.value} data is blocked from external AI providers"
            )
        return cast(AuthorizedInput, redact_external_data(value))

    @classmethod
    def _authorized_parts(
        cls,
        parts: list[AIInputPart],
        classification: DataClassification,
        external_consent: bool,
        external: bool,
    ) -> list[AIInputPart]:
        cls._authorize_input({}, classification, external_consent, external)
        if not external:
            return parts
        return [
            part.model_copy(
                update={
                    "value": (
                        cast(str, redact_external_data(part.value))
                        if part.kind == "text"
                        else part.value
                    )
                }
            )
            for part in parts
        ]

    @staticmethod
    def _validated_content(
        content: str, schema: dict[str, object] | None
    ) -> str | dict[str, object] | list[object]:
        if schema is None:
            return content
        try:
            parsed: object = json.loads(content)
            Draft202012Validator(schema).validate(parsed)
        except (json.JSONDecodeError, ValidationError) as error:
            raise AIGatewayValidationError("Model output failed structured validation") from error
        if not isinstance(parsed, (dict, list)):
            raise AIGatewayValidationError("Structured model output must be an object or array")
        return parsed

    @staticmethod
    def _cost(model: AIModelDefinition, input_tokens: int, output_tokens: int) -> int:
        numerator = (
            input_tokens * model.input_cost_micros_per_million
            + output_tokens * model.output_cost_micros_per_million
        )
        return (numerator + 999_999) // 1_000_000

    @staticmethod
    def _hash(value: object) -> str:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _cache_key(self, request: AIGatewayRequest, prompt: PromptTemplate, model_id: str) -> str:
        return self._hash(
            {
                "profile": request.profile_id,
                "source": request.source_version,
                "model": model_id,
                "prompt": prompt.version,
                "schema": prompt.schema_version,
                "privacy": request.classification.value,
                "task": request.task_type.value,
                "input": request.input_data,
                "output_schema": request.output_schema,
            }
        )

    def _read_cache(self, key: str) -> AIGatewayResponse | None:
        record = self._repository.get_cache(key)
        if record is None or _aware(record.expires_at) <= datetime.now(UTC):
            return None
        payload = self._cipher.decrypt_json(record.encrypted_response, context=f"ai-cache:{key}")
        return AIGatewayResponse.model_validate(payload)

    def _write_cache(
        self,
        response: AIGatewayResponse,
        request: AIGatewayRequest,
        key: str,
        ttl_seconds: int,
    ) -> None:
        now = datetime.now(UTC)
        self._repository.upsert_cache(
            AICacheRecord(
                key=key,
                profile_id=request.profile_id,
                classification=request.classification,
                encrypted_response=self._cipher.encrypt_json(
                    response.model_dump(mode="json"), context=f"ai-cache:{key}"
                ),
                expires_at=now + timedelta(seconds=ttl_seconds),
                created_at=now,
            )
        )

    def _record(
        self,
        response: AIGatewayResponse,
        request: AIGatewayRequest,
        input_hash: str,
        cache_key: str,
        route: list[str],
        started_at: datetime,
        started_clock: float,
        *,
        status: str,
        error_code: str | None = None,
    ) -> None:
        self._repository.add_invocation(
            AIInvocationRecord(
                id=response.invocation_id,
                profile_id=request.profile_id,
                task_type=request.task_type,
                provider_id=response.provider_id,
                model_id=response.model_id,
                prompt_version=response.prompt_version,
                schema_version=response.schema_version,
                input_hash=input_hash,
                cache_key=cache_key,
                classification=request.classification,
                status=status,
                attempts=response.attempts,
                route=route,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_micros=response.usage.cost_micros,
                latency_ms=max(0, round((time.monotonic() - started_clock) * 1_000)),
                error_code=error_code,
                created_at=started_at,
                completed_at=datetime.now(UTC),
            )
        )


class AgentService:
    def __init__(self, gateway: AIGatewayService) -> None:
        self._gateway = gateway

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        task = AGENT_TASKS[request.role]
        response = self._gateway.invoke(
            AIGatewayRequest(
                task_type=task,
                prompt_id=f"agent.{request.role.value.casefold()}",
                input_data=request.input_data,
                output_schema=AGENT_SCHEMAS[request.role],
                profile_id=request.profile_id,
                source_version=request.source_version,
                classification=request.classification,
                external_consent=request.external_consent,
            )
        )
        if not isinstance(response.content, dict):
            raise AIGatewayValidationError("Agent returned non-object content")
        return AgentRunResult(role=request.role, output=response.content, gateway=response)


class AIEvaluationHarness:
    def __init__(self, agents: AgentService) -> None:
        self._agents = agents

    def run(self, cases: list[EvaluationCase]) -> EvaluationReport:
        results: list[EvaluationCaseResult] = []
        for case in cases:
            failures: list[str] = []
            invocation_id: str | None = None
            try:
                result = self._agents.run(case.agent_request)
                invocation_id = result.gateway.invocation_id
                failures.extend(
                    f"missing key: {key}"
                    for key in sorted(case.required_keys - result.output.keys())
                )
                failures.extend(
                    f"unexpected {key}"
                    for key, expected in case.expected_values.items()
                    if result.output.get(key) != expected
                )
            except AIGatewayError as error:
                failures.append(type(error).__name__)
            results.append(
                EvaluationCaseResult(
                    case_id=case.id,
                    passed=not failures,
                    failures=failures,
                    invocation_id=invocation_id,
                )
            )
        passed = sum(item.passed for item in results)
        return EvaluationReport(
            total=len(results), passed=passed, failed=len(results) - passed, cases=results
        )
