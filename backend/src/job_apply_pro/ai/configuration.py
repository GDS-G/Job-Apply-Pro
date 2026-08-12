from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from job_apply_pro.ai.providers import AIProviderRuntime, GeminiProvider, OpenAICompatibleProvider
from job_apply_pro.ai.registry import AIRegistry
from job_apply_pro.domain.ai import (
    AIModelDefinition,
    AIProviderDefinition,
    AIRoutingPolicy,
    ProviderKind,
)


class AIProviderConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: AIProviderDefinition
    api_key: SecretStr | None = None


class AIConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: list[AIProviderConfiguration] = Field(max_length=20)
    models: list[AIModelDefinition] = Field(max_length=100)
    policies: list[AIRoutingPolicy] = Field(max_length=50)


def build_ai_registry(config_json: SecretStr | None) -> AIRegistry:
    if config_json is None:
        return AIRegistry([], [], [])
    config = AIConfiguration.model_validate_json(config_json.get_secret_value())
    providers = [
        (
            GeminiProvider(AIProviderRuntime(definition=item.definition, api_key=item.api_key))
            if item.definition.kind is ProviderKind.GEMINI
            else OpenAICompatibleProvider(
                AIProviderRuntime(definition=item.definition, api_key=item.api_key)
            )
        )
        for item in config.providers
    ]
    return AIRegistry(providers, config.models, config.policies)
