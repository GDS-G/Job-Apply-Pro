from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from typing import NoReturn, TypeVar, cast
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError
from pydantic import ValidationError as PydanticValidationError

from job_apply_pro.ai.prompts import (
    AGENT_SCHEMAS,
    AGENT_TASKS,
    default_prompt_registry,
    redact_external_data,
    render_prompt,
)
from job_apply_pro.ai.providers import (
    AIProviderError,
    AIProviderMediaRetentionError,
    AIProviderNotAppliedError,
    AIProviderRejectedError,
    AIProviderResponseError,
    AIProviderUncertainError,
)
from job_apply_pro.ai.registry import AIRegistry
from job_apply_pro.domain.ai import (
    AgentRunRequest,
    AgentRunResult,
    AICacheRecord,
    AICapability,
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
from job_apply_pro.domain.external_effects import ExternalEffectKind, ExternalEffectStatus
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.services.external_effects import (
    ExternalEffectConsumedError,
    ExternalEffectService,
)
from job_apply_pro.storage.external_effect_repository import ExternalEffectConflictError
from job_apply_pro.storage.repository_contracts import AIGatewayRepositoryProtocol


class AIGatewayError(RuntimeError):
    pass


class AIGatewayPolicyError(AIGatewayError):
    pass


class AIGatewayValidationError(AIGatewayError):
    pass


class AIGatewayUnavailableError(AIGatewayError):
    pass


class AIGatewayUncertainError(AIGatewayUnavailableError):
    """A provider response was lost or incomplete; no automatic retry is safe."""


class AIGatewayMediaRetentionError(AIGatewayUnavailableError):
    """A remote media outcome is unresolved; never retry this invocation automatically."""


AuthorizedInput = TypeVar("AuthorizedInput")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class AIGatewayService:
    def __init__(
        self,
        registry: AIRegistry,
        repository: AIGatewayRepositoryProtocol,
        cipher: SensitiveDataCipher,
        external_effects: ExternalEffectService,
        prompts: dict[str, PromptTemplate] | None = None,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._cipher = cipher
        self._external_effects = external_effects
        self._prompts = prompts or default_prompt_registry()

    def providers(self) -> list[object]:
        return [item.model_dump(mode="json") for item in self._registry.provider_definitions()]

    def models(self) -> list[object]:
        return [item.model_dump(mode="json") for item in self._registry.model_definitions()]

    def invoke(self, request: AIGatewayRequest) -> AIGatewayResponse:
        if (
            any(part.kind == "media" for part in request.input_parts)
            and not request.media_upload_consent
        ):
            raise AIGatewayPolicyError("Media upload requires explicit current consent")
        prompt = self._prompt(request)
        self._validate_request_tools(request, prompt)
        routes = self._registry.routes(
            request.task_type,
            {AICapability.MULTIMODAL}
            if any(part.kind in {"image_url", "media"} for part in request.input_parts)
            else None,
        )
        route_ids = [model.id for _, model in routes]
        started_at = datetime.now(UTC)
        started_clock = time.monotonic()
        input_hash = self._hash(
            {
                "input": request.input_data,
                "parts": self._input_part_fingerprints(request.input_parts),
            }
        )
        attempts = 0
        last_error: Exception | None = None
        last_provider = routes[-1][0].definition.id
        last_model = routes[-1][1].id
        last_cache_key = self._cache_key(request, prompt, last_model)
        operation_id: str | None = None
        last_attempt_id: str | None = None
        last_effect_status: ExternalEffectStatus | None = None
        stop_routing = False
        effect_request = {
            "task_type": request.task_type.value,
            "prompt_version": prompt.version,
            "schema_version": prompt.schema_version,
            "profile_id": request.profile_id,
            "source_version": request.source_version,
            "classification": request.classification.value,
            "input_hash": input_hash,
            "route": route_ids,
            "cache_mode": request.cache_mode,
            "output_schema_hash": self._hash(request.output_schema),
            "tools": [
                {
                    "name": tool.name,
                    "schema_hash": self._hash(tool.input_schema),
                }
                for tool in request.tools
            ],
            "external_consent": request.external_consent,
            "media_upload_consent": request.media_upload_consent,
            "max_cost_micros": request.max_cost_micros,
            "timeout_seconds": request.timeout_seconds,
        }
        effect_subject = self._external_effects.request_fingerprint(effect_request)
        effect_key = request.effect_key or f"ai-completion:{effect_subject}"

        for route_index, (provider, model) in enumerate(routes):
            last_provider, last_model = provider.definition.id, model.id
            cache_key = self._cache_key(request, prompt, model.id)
            last_cache_key = cache_key
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

            system, user = render_prompt(prompt, prepared_input)
            policy = self._registry.policy(request.task_type)
            timeout = min(request.timeout_seconds or policy.timeout_seconds, policy.timeout_seconds)
            for attempt in range(policy.retries_per_model + 1):
                attempts += 1
                repair = (
                    "\nPrevious output failed schema validation. Return only corrected JSON."
                    if attempt
                    else ""
                )
                provider_request = AIProviderRequest(
                    model=model.model,
                    system_instruction=system + repair,
                    user_content=user,
                    input_parts=prepared_parts,
                    tools=request.tools,
                    output_schema=request.output_schema,
                    media_upload_consent=request.media_upload_consent,
                    timeout_seconds=timeout,
                )
                if operation_id is None:
                    self._repository.release_transaction()
                    try:
                        admission = self._external_effects.admit(
                            effect_key=effect_key,
                            kind=ExternalEffectKind.AI_COMPLETION,
                            subject_type="ai_request",
                            subject_id=effect_subject,
                            actor="ai-gateway",
                            request=effect_request,
                        )
                        operation_id = self._external_effects.require_fresh(admission).operation.id
                    except (
                        ExternalEffectConflictError,
                        ExternalEffectConsumedError,
                    ) as error:
                        raise AIGatewayUnavailableError(
                            "AI request admission is already consumed or requires reconciliation"
                        ) from error
                attempt_request = {
                    "provider_id": provider.definition.id,
                    "model_id": model.id,
                    "model": model.model,
                    "cache_key": cache_key,
                    "repair_attempt": attempt,
                    "timeout_seconds": timeout,
                }
                try:
                    effect_attempt = self._external_effects.prepare_attempt(
                        operation_id,
                        provider=provider.definition.id,
                        target_code=model.id,
                        request=attempt_request,
                    )
                    last_attempt_id = effect_attempt.id
                    self._external_effects.begin_dispatch(operation_id, effect_attempt.id)
                except ExternalEffectConflictError as error:
                    raise AIGatewayUnavailableError(
                        "AI request attempt ownership changed; automatic retry is blocked"
                    ) from error
                more_attempts = attempt < policy.retries_per_model or route_index < len(routes) - 1
                try:
                    raw = provider.complete(provider_request)
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
                        invocation_id=effect_attempt.id,
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
                    try:
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
                    except Exception as error:
                        self._raise_local_evidence_failure(
                            operation_id, effect_attempt.id, cause=error
                        )
                    try:
                        if request.cache_mode != "BYPASS" and policy.cache_ttl_seconds:
                            self._write_cache(
                                response, request, cache_key, policy.cache_ttl_seconds
                            )
                    except Exception:
                        # Cache population is optional after the invocation row is durable.
                        pass
                    self._external_effects.finish(
                        operation_id,
                        effect_attempt.id,
                        status=ExternalEffectStatus.CONFIRMED,
                        result_reference=f"model-invocation:{effect_attempt.id}",
                        result={
                            "status": "SUCCEEDED",
                            "input_tokens": raw.input_tokens,
                            "output_tokens": raw.output_tokens,
                        },
                        input_tokens=raw.input_tokens,
                        output_tokens=raw.output_tokens,
                        cost_micros=cost,
                    )
                    return response
                except AIGatewayUncertainError:
                    raise
                except AIProviderMediaRetentionError as error:
                    last_error = error
                    last_effect_status = ExternalEffectStatus.UNCERTAIN
                    stop_routing = True
                    break
                except AIProviderUncertainError as error:
                    last_error = error
                    last_effect_status = ExternalEffectStatus.UNCERTAIN
                    stop_routing = True
                    break
                except (AIProviderResponseError, AIGatewayValidationError) as error:
                    last_error = error
                    last_effect_status = ExternalEffectStatus.CONFIRMED
                    if more_attempts:
                        self._external_effects.finish(
                            operation_id,
                            effect_attempt.id,
                            status=ExternalEffectStatus.CONFIRMED,
                            result_reference=f"provider-response:{effect_attempt.id}",
                            result={"status": "INVALID_RESPONSE"},
                            continue_operation=True,
                        )
                        continue
                    break
                except AIGatewayPolicyError as error:
                    last_error = error
                    last_effect_status = ExternalEffectStatus.CONFIRMED
                    stop_routing = True
                    break
                except AIProviderError as error:
                    last_error = error
                    last_effect_status = ExternalEffectStatus.FAILED
                    if more_attempts:
                        self._external_effects.finish(
                            operation_id,
                            effect_attempt.id,
                            status=ExternalEffectStatus.FAILED,
                            error_code=self._provider_error_code(error),
                            continue_operation=True,
                        )
                        continue
                    break
                except Exception as error:
                    last_error = error
                    last_effect_status = ExternalEffectStatus.UNCERTAIN
                    stop_routing = True
                    break

            if stop_routing:
                break

        error_code = self._provider_error_code(last_error)
        failed = AIGatewayResponse(
            invocation_id=last_attempt_id or str(uuid4()),
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
        try:
            self._record(
                failed,
                request,
                input_hash,
                last_cache_key,
                route_ids,
                started_at,
                started_clock,
                status=(
                    "UNCERTAIN"
                    if last_effect_status is ExternalEffectStatus.UNCERTAIN
                    else "FAILED"
                ),
                error_code=error_code,
            )
        except Exception as error:
            if operation_id is not None and last_attempt_id is not None:
                self._raise_local_evidence_failure(operation_id, last_attempt_id, cause=error)
            raise AIGatewayUnavailableError(
                "AI invocation evidence could not be persisted"
            ) from error
        if operation_id is not None and last_attempt_id is not None:
            terminal_status = last_effect_status or ExternalEffectStatus.UNCERTAIN
            if terminal_status is ExternalEffectStatus.CONFIRMED:
                self._external_effects.finish(
                    operation_id,
                    last_attempt_id,
                    status=terminal_status,
                    result_reference=f"model-invocation:{last_attempt_id}",
                    result={"status": "FAILED", "error_code": error_code},
                )
            else:
                self._external_effects.finish(
                    operation_id,
                    last_attempt_id,
                    status=terminal_status,
                    error_code=error_code,
                )
        if isinstance(last_error, AIGatewayPolicyError):
            raise last_error
        if isinstance(last_error, AIProviderMediaRetentionError):
            raise AIGatewayMediaRetentionError(
                "AI media retention is unresolved; automatic retries and fallback stopped. "
                "Review provider file retention before another request."
            ) from last_error
        if isinstance(last_error, AIProviderUncertainError) or not isinstance(
            last_error,
            (AIProviderError, AIGatewayValidationError, AIGatewayPolicyError),
        ):
            raise AIGatewayUncertainError(
                "AI provider response is uncertain; automatic retries and fallback stopped"
            ) from last_error
        raise AIGatewayUnavailableError("Every configured AI route failed safely") from last_error

    def embed(self, request: AIEmbeddingRequest) -> AIEmbeddingResponse:
        routes = self._registry.embedding_routes()
        route_ids = [model.id for _, model in routes]
        started_at = datetime.now(UTC)
        started_clock = time.monotonic()
        input_hash = self._hash({"texts": request.texts})
        effect_request = {
            "task_type": AITaskType.EMBEDDING.value,
            "profile_id": request.profile_id,
            "classification": request.classification.value,
            "input_hash": input_hash,
            "route": route_ids,
            "external_consent": request.external_consent,
        }
        effect_subject = self._external_effects.request_fingerprint(effect_request)
        effect_key = request.effect_key or f"ai-embedding:{effect_subject}"
        operation_id: str | None = None
        last_attempt_id: str | None = None
        last_provider = routes[-1][0].definition.id
        last_model = routes[-1][1].id
        last_error: Exception | None = None
        last_effect_status: ExternalEffectStatus | None = None
        attempts = 0

        for route_index, (provider, model) in enumerate(routes):
            last_provider, last_model = provider.definition.id, model.id
            try:
                texts = self._authorize_input(
                    request.texts,
                    request.classification,
                    request.external_consent,
                    provider.definition.external,
                )
            except AIGatewayPolicyError as error:
                last_error = error
                continue
            if operation_id is None:
                self._repository.release_transaction()
                try:
                    admission = self._external_effects.admit(
                        effect_key=effect_key,
                        kind=ExternalEffectKind.AI_EMBEDDING,
                        subject_type="ai_request",
                        subject_id=effect_subject,
                        actor="ai-gateway",
                        request=effect_request,
                    )
                    operation_id = self._external_effects.require_fresh(admission).operation.id
                except (
                    ExternalEffectConflictError,
                    ExternalEffectConsumedError,
                ) as error:
                    raise AIGatewayUnavailableError(
                        "AI embedding admission is already consumed or requires reconciliation"
                    ) from error
            attempt_request = {
                "provider_id": provider.definition.id,
                "model_id": model.id,
                "model": model.model,
                "input_hash": input_hash,
                "timeout_seconds": 30,
            }
            try:
                effect_attempt = self._external_effects.prepare_attempt(
                    operation_id,
                    provider=provider.definition.id,
                    target_code=model.id,
                    request=attempt_request,
                )
                last_attempt_id = effect_attempt.id
                attempts += 1
                self._external_effects.begin_dispatch(operation_id, effect_attempt.id)
            except ExternalEffectConflictError as error:
                raise AIGatewayUnavailableError(
                    "AI embedding attempt ownership changed; automatic retry is blocked"
                ) from error
            try:
                vectors = provider.embed(model.model, list(texts), 30)
                response = AIEmbeddingResponse(
                    provider_id=provider.definition.id,
                    model_id=model.id,
                    vectors=vectors,
                    usage=AIUsage(),
                )
                try:
                    self._record_embedding(
                        invocation_id=effect_attempt.id,
                        request=request,
                        response=response,
                        input_hash=input_hash,
                        route=route_ids,
                        attempts=attempts,
                        started_at=started_at,
                        started_clock=started_clock,
                        status="SUCCEEDED",
                    )
                except Exception as error:
                    self._raise_local_evidence_failure(operation_id, effect_attempt.id, cause=error)
                self._external_effects.finish(
                    operation_id,
                    effect_attempt.id,
                    status=ExternalEffectStatus.CONFIRMED,
                    result_reference=f"model-invocation:{effect_attempt.id}",
                    result={
                        "status": "SUCCEEDED",
                        "vector_count": len(vectors),
                    },
                )
                return response
            except AIGatewayUncertainError:
                raise
            except AIProviderUncertainError as error:
                last_error = error
                last_effect_status = ExternalEffectStatus.UNCERTAIN
                break
            except AIProviderResponseError as error:
                last_error = error
                last_effect_status = ExternalEffectStatus.CONFIRMED
            except AIProviderError as error:
                last_error = error
                last_effect_status = ExternalEffectStatus.FAILED
            except Exception as error:
                last_error = error
                last_effect_status = ExternalEffectStatus.UNCERTAIN
                break

            if route_index < len(routes) - 1:
                if last_effect_status is ExternalEffectStatus.CONFIRMED:
                    self._external_effects.finish(
                        operation_id,
                        effect_attempt.id,
                        status=ExternalEffectStatus.CONFIRMED,
                        result_reference=f"provider-response:{effect_attempt.id}",
                        result={"status": "INVALID_RESPONSE"},
                        continue_operation=True,
                    )
                else:
                    self._external_effects.finish(
                        operation_id,
                        effect_attempt.id,
                        status=ExternalEffectStatus.FAILED,
                        error_code=self._provider_error_code(last_error),
                        continue_operation=True,
                    )

        error_code = self._provider_error_code(last_error)
        if operation_id is not None and last_attempt_id is not None:
            terminal_status = last_effect_status or ExternalEffectStatus.UNCERTAIN
            try:
                self._record_embedding(
                    invocation_id=last_attempt_id,
                    request=request,
                    response=None,
                    input_hash=input_hash,
                    route=route_ids,
                    attempts=attempts,
                    started_at=started_at,
                    started_clock=started_clock,
                    status=(
                        "UNCERTAIN"
                        if terminal_status is ExternalEffectStatus.UNCERTAIN
                        else "FAILED"
                    ),
                    provider_id=last_provider,
                    model_id=last_model,
                    error_code=error_code,
                )
            except Exception as error:
                self._raise_local_evidence_failure(operation_id, last_attempt_id, cause=error)
            if terminal_status is ExternalEffectStatus.CONFIRMED:
                self._external_effects.finish(
                    operation_id,
                    last_attempt_id,
                    status=terminal_status,
                    result_reference=f"model-invocation:{last_attempt_id}",
                    result={"status": "FAILED", "error_code": error_code},
                )
            else:
                self._external_effects.finish(
                    operation_id,
                    last_attempt_id,
                    status=terminal_status,
                    error_code=error_code,
                )
        if isinstance(last_error, AIProviderUncertainError) or not isinstance(
            last_error, (AIProviderError, AIGatewayPolicyError)
        ):
            raise AIGatewayUncertainError(
                "AI embedding response is uncertain; automatic fallback stopped"
            ) from last_error
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
        try:
            items = cast(list[object], response.content["results"])
            results = [AIRerankResult.model_validate(item) for item in items]
        except (KeyError, TypeError, PydanticValidationError) as error:
            raise AIGatewayValidationError("Reranker returned invalid results") from error
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
                "parts": self._input_part_fingerprints(request.input_parts),
                "output_schema": request.output_schema,
            }
        )

    @staticmethod
    def _input_part_fingerprints(parts: list[AIInputPart]) -> list[dict[str, object]]:
        return [
            {
                "kind": part.kind,
                "mime_type": part.mime_type,
                "display_name": part.display_name,
                "value_hash": hashlib.sha256((part.value or "").encode()).hexdigest()
                if part.value is not None
                else None,
                "data_hash": hashlib.sha256(part.data).hexdigest()
                if part.data is not None
                else None,
                "data_bytes": len(part.data) if part.data is not None else 0,
            }
            for part in parts
        ]

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

    @staticmethod
    def _provider_error_code(error: Exception | None) -> str:
        if error is None:
            return "NO_ROUTE"
        if isinstance(error, AIProviderMediaRetentionError):
            return "MEDIA_RETENTION_UNRESOLVED"
        if isinstance(error, AIProviderUncertainError):
            return "PROVIDER_RESPONSE_UNCERTAIN"
        if isinstance(error, AIProviderRejectedError):
            return "PROVIDER_REJECTED"
        if isinstance(error, AIProviderNotAppliedError):
            return "PROVIDER_NOT_APPLIED"
        if isinstance(error, (AIProviderResponseError, AIGatewayValidationError)):
            return "PROVIDER_RESPONSE_INVALID"
        if isinstance(error, AIGatewayPolicyError):
            return "POLICY_REJECTED"
        if isinstance(error, AIProviderError):
            return "PROVIDER_FAILED"
        return "PROVIDER_OUTCOME_UNCERTAIN"

    def _raise_local_evidence_failure(
        self,
        operation_id: str,
        attempt_id: str,
        *,
        cause: Exception,
    ) -> NoReturn:
        """Fence a dispatched provider call when its local audit row is not durable."""

        try:
            self._external_effects.finish(
                operation_id,
                attempt_id,
                status=ExternalEffectStatus.UNCERTAIN,
                error_code="LOCAL_EVIDENCE_PERSIST_FAILED",
            )
        except Exception as ledger_error:
            raise AIGatewayUncertainError(
                "AI provider outcome requires reconciliation because local evidence and "
                "effect-ledger finalization failed"
            ) from ledger_error
        raise AIGatewayUncertainError(
            "AI provider outcome requires reconciliation because local evidence could not be "
            "persisted"
        ) from cause

    def _record_embedding(
        self,
        *,
        invocation_id: str,
        request: AIEmbeddingRequest,
        response: AIEmbeddingResponse | None,
        input_hash: str,
        route: list[str],
        attempts: int,
        started_at: datetime,
        started_clock: float,
        status: str,
        provider_id: str | None = None,
        model_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._repository.add_invocation(
            AIInvocationRecord(
                id=invocation_id,
                profile_id=request.profile_id,
                task_type=AITaskType.EMBEDDING,
                provider_id=response.provider_id if response is not None else provider_id or "none",
                model_id=response.model_id if response is not None else model_id or "none",
                prompt_version="embedding-v1",
                schema_version="vectors-v1",
                input_hash=input_hash,
                cache_key=input_hash,
                classification=request.classification,
                status=status,
                attempts=attempts,
                route=route,
                input_tokens=0,
                output_tokens=0,
                cost_micros=0,
                latency_ms=max(0, round((time.monotonic() - started_clock) * 1_000)),
                error_code=error_code,
                created_at=started_at,
                completed_at=datetime.now(UTC),
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

    def run(
        self,
        request: AgentRunRequest,
        *,
        bypass_cache: bool = False,
        effect_key: str | None = None,
    ) -> AgentRunResult:
        task = AGENT_TASKS[request.role]
        response = self._gateway.invoke(
            AIGatewayRequest(
                effect_key=effect_key or request.effect_key,
                task_type=task,
                prompt_id=f"agent.{request.role.value.casefold()}",
                input_data=request.input_data,
                output_schema=AGENT_SCHEMAS[request.role],
                profile_id=request.profile_id,
                source_version=request.source_version,
                classification=request.classification,
                external_consent=request.external_consent,
                cache_mode="BYPASS" if bypass_cache else "USE",
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
            invocation_ids: list[str] = []
            outputs: list[dict[str, object]] = []
            case_key = hashlib.sha256(case.id.encode()).hexdigest()
            for repeat_index in range(case.repeat_count):
                try:
                    result = self._agents.run(
                        case.agent_request,
                        bypass_cache=case.repeat_count > 1,
                        effect_key=f"evaluation:{case_key}:{repeat_index}",
                    )
                except AIGatewayError as error:
                    failures.append(type(error).__name__)
                    continue
                invocation_ids.append(result.gateway.invocation_id)
                outputs.append(result.output)

            output_fingerprint: str | None = None
            if outputs:
                output = outputs[0]
                output_fingerprint = self._output_fingerprint(output)
                failures.extend(
                    f"missing key: {key}" for key in sorted(case.required_keys - output.keys())
                )
                failures.extend(
                    f"unexpected {key}"
                    for key, expected in case.expected_values.items()
                    if output.get(key) != expected
                )
                for pointer in sorted(case.required_json_pointers):
                    found, _ = self._resolve_json_pointer(output, pointer)
                    if not found:
                        failures.append(f"missing JSON pointer: {pointer}")
                for pointer, expected in sorted(case.expected_json_pointer_values.items()):
                    found, actual = self._resolve_json_pointer(output, pointer)
                    if not found or actual != expected:
                        failures.append(f"unexpected JSON pointer: {pointer}")
                if case.allowed_evidence_ids:
                    found, evidence = self._resolve_json_pointer(output, case.evidence_json_pointer)
                    if not found or not isinstance(evidence, list):
                        failures.append(f"missing evidence list: {case.evidence_json_pointer}")
                    elif any(
                        not isinstance(value, str) or value not in case.allowed_evidence_ids
                        for value in evidence
                    ):
                        failures.append(f"evidence outside allowlist: {case.evidence_json_pointer}")
                serialized = json.dumps(
                    output, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).casefold()
                failures.extend(
                    f"forbidden output term matched: {index}"
                    for index, term in enumerate(case.forbidden_output_terms)
                    if term.casefold() in serialized
                )
                fingerprints = {self._output_fingerprint(value) for value in outputs}
                if len(fingerprints) > 1:
                    failures.append("output changed across independent evaluation runs")
            results.append(
                EvaluationCaseResult(
                    case_id=case.id,
                    passed=not failures,
                    failures=failures,
                    invocation_id=invocation_ids[0] if invocation_ids else None,
                    invocation_ids=invocation_ids,
                    output_fingerprint=output_fingerprint,
                )
            )
        passed = sum(item.passed for item in results)
        return EvaluationReport(
            total=len(results), passed=passed, failed=len(results) - passed, cases=results
        )

    @staticmethod
    def _output_fingerprint(output: dict[str, object]) -> str:
        return hashlib.sha256(
            json.dumps(output, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _resolve_json_pointer(value: object, pointer: str) -> tuple[bool, object | None]:
        if pointer == "":
            return True, value
        if not pointer.startswith("/"):
            return False, None
        current = value
        for raw_token in pointer[1:].split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and token in current:
                current = current[token]
            elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
                current = current[int(token)]
            else:
                return False, None
        return True, current
