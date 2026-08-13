from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ProviderKind(StrEnum):
    OPENAI_COMPATIBLE = "OPENAI_COMPATIBLE"
    SECONDARY_COMPATIBLE = "SECONDARY_COMPATIBLE"
    GEMINI = "GEMINI"
    LLAMA_CPP = "LLAMA_CPP"


class DataClassification(StrEnum):
    ROUTINE = "ROUTINE"
    EMPLOYMENT_SENSITIVE = "EMPLOYMENT_SENSITIVE"
    HIGHLY_SENSITIVE = "HIGHLY_SENSITIVE"
    RESTRICTED = "RESTRICTED"


class AITaskType(StrEnum):
    COORDINATION = "COORDINATION"
    QUALIFICATION = "QUALIFICATION"
    FORM_INTERPRETATION = "FORM_INTERPRETATION"
    ANSWER = "ANSWER"
    VERIFICATION = "VERIFICATION"
    RECOVERY = "RECOVERY"
    EMBEDDING = "EMBEDDING"
    RERANKING = "RERANKING"


class AICapability(StrEnum):
    TEXT = "TEXT"
    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    FUNCTION_CALLING = "FUNCTION_CALLING"
    MULTIMODAL = "MULTIMODAL"
    EMBEDDING = "EMBEDDING"
    RERANKING = "RERANKING"


class AIProviderDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=80)
    kind: ProviderKind
    base_url: HttpUrl
    external: bool = True
    enabled: bool = True
    retention_policy: str = Field(default="provider-configured", max_length=120)


class AIModelDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=120)
    provider_id: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    capabilities: set[AICapability]
    context_window: int = Field(ge=1_024, le=10_000_000)
    input_cost_micros_per_million: int = Field(default=0, ge=0)
    output_cost_micros_per_million: int = Field(default=0, ge=0)
    enabled: bool = True


class AIRoutingPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_type: AITaskType
    model_order: list[str] = Field(min_length=1, max_length=20)
    required_capabilities: set[AICapability]
    allow_external: bool = False
    max_cost_micros: int = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=30, ge=1, le=300)
    retries_per_model: int = Field(default=1, ge=0, le=3)
    cache_ttl_seconds: int = Field(default=3_600, ge=0, le=2_592_000)


class PromptTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=100)
    task_type: AITaskType
    version: str = Field(min_length=1, max_length=40)
    schema_version: str = Field(min_length=1, max_length=40)
    system_instruction: str = Field(min_length=1, max_length=20_000)
    user_template: str = Field(min_length=1, max_length=20_000)
    allowed_tools: list[str] = Field(default_factory=list, max_length=20)
    decision_rules: list[str] = Field(default_factory=list, max_length=50)
    stopping_conditions: list[str] = Field(default_factory=list, max_length=20)


class AIInputPart(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["text", "image_url"]
    value: str = Field(min_length=1, max_length=5_000_000)


class AIToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: str = Field(min_length=1, max_length=1_000)
    input_schema: dict[str, object]


class AIToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    arguments: dict[str, object]


class AIGatewayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: AITaskType
    prompt_id: str = Field(min_length=1, max_length=100)
    input_data: dict[str, object]
    input_parts: list[AIInputPart] = Field(default_factory=list, max_length=20)
    tools: list[AIToolDefinition] = Field(default_factory=list, max_length=20)
    output_schema: dict[str, object] | None = None
    profile_id: str | None = Field(default=None, max_length=80)
    source_version: str = Field(default="none", max_length=100)
    classification: DataClassification = DataClassification.ROUTINE
    external_consent: bool = False
    max_cost_micros: int | None = Field(default=None, ge=0)
    timeout_seconds: float | None = Field(default=None, ge=1, le=300)
    cache_mode: Literal["USE", "BYPASS", "REFRESH"] = "USE"


class AIUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_micros: int = Field(default=0, ge=0)


class AIGatewayResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    invocation_id: str
    task_type: AITaskType
    provider_id: str
    model_id: str
    content: str | dict[str, object] | list[object]
    tool_calls: list[AIToolCall] = Field(default_factory=list)
    usage: AIUsage
    cached: bool = False
    attempts: int = Field(ge=0)
    schema_valid: bool
    prompt_version: str
    schema_version: str
    classification: DataClassification
    created_at: datetime


class AIProviderRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    system_instruction: str
    user_content: str
    input_parts: list[AIInputPart] = Field(default_factory=list, max_length=20)
    tools: list[AIToolDefinition] = Field(default_factory=list, max_length=20)
    output_schema: dict[str, object] | None = None
    timeout_seconds: float = Field(ge=1, le=300)


class AIProviderResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    tool_calls: list[AIToolCall] = Field(default_factory=list)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class AIEmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texts: list[str] = Field(min_length=1, max_length=128)
    profile_id: str | None = None
    classification: DataClassification = DataClassification.ROUTINE
    external_consent: bool = False


class AIEmbeddingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_id: str
    model_id: str
    vectors: list[list[float]]
    usage: AIUsage


class AIRerankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=20_000)
    documents: list[str] = Field(min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=100)
    profile_id: str | None = None
    classification: DataClassification = DataClassification.ROUTINE
    external_consent: bool = False


class AIRerankResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    score: float = Field(ge=0, le=1)


class AgentRole(StrEnum):
    COORDINATOR = "COORDINATOR"
    QUALIFICATION = "QUALIFICATION"
    FORM_INTERPRETATION = "FORM_INTERPRETATION"
    ANSWER = "ANSWER"
    VERIFICATION = "VERIFICATION"
    RECOVERY = "RECOVERY"


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole
    input_data: dict[str, object]
    profile_id: str | None = None
    source_version: str = "none"
    classification: DataClassification = DataClassification.ROUTINE
    external_consent: bool = False


class AgentRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: AgentRole
    output: dict[str, object]
    gateway: AIGatewayResponse


class EvaluationCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=100)
    agent_request: AgentRunRequest
    required_keys: set[str] = Field(default_factory=set)
    expected_values: dict[str, object] = Field(default_factory=dict)
    required_json_pointers: set[str] = Field(default_factory=set, max_length=50)
    expected_json_pointer_values: dict[str, object] = Field(default_factory=dict)
    allowed_evidence_ids: set[str] = Field(default_factory=set, max_length=200)
    evidence_json_pointer: str = Field(default="/evidence_claim_ids", max_length=500)
    forbidden_output_terms: list[str] = Field(default_factory=list, max_length=50)
    repeat_count: int = Field(default=1, ge=1, le=5)


class EvaluationCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    passed: bool
    failures: list[str]
    invocation_id: str | None = None
    invocation_ids: list[str] = Field(default_factory=list, max_length=5)
    output_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)


class EvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    passed: int
    failed: int
    cases: list[EvaluationCaseResult]


class AIInvocationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str | None = None
    task_type: AITaskType
    provider_id: str
    model_id: str
    prompt_version: str
    schema_version: str
    input_hash: str
    cache_key: str
    classification: DataClassification
    status: str
    attempts: int = Field(ge=0)
    route: list[str]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_micros: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    error_code: str | None = None
    created_at: datetime
    completed_at: datetime


class AICacheRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    profile_id: str | None = None
    classification: DataClassification
    encrypted_response: str
    expires_at: datetime
    created_at: datetime
