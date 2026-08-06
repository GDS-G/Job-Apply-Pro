from __future__ import annotations

from collections.abc import Iterable

from job_apply_pro.ai.providers import AIProviderProtocol
from job_apply_pro.domain.ai import (
    AICapability,
    AIModelDefinition,
    AIProviderDefinition,
    AIRoutingPolicy,
    AITaskType,
)


class AIRegistryError(RuntimeError):
    pass


class AIRegistry:
    def __init__(
        self,
        providers: Iterable[AIProviderProtocol],
        models: Iterable[AIModelDefinition],
        policies: Iterable[AIRoutingPolicy],
    ) -> None:
        self._providers = {provider.definition.id: provider for provider in providers}
        self._definitions = {provider.definition.id: provider.definition for provider in providers}
        self._models = {model.id: model for model in models}
        self._policies = {policy.task_type: policy for policy in policies}
        self._validate()

    def provider_definitions(self) -> list[AIProviderDefinition]:
        return sorted(self._definitions.values(), key=lambda item: item.id)

    def model_definitions(self) -> list[AIModelDefinition]:
        return sorted(self._models.values(), key=lambda item: item.id)

    def policy(self, task_type: AITaskType) -> AIRoutingPolicy:
        try:
            return self._policies[task_type]
        except KeyError as error:
            raise AIRegistryError(f"No routing policy exists for {task_type}") from error

    def routes(self, task_type: AITaskType) -> list[tuple[AIProviderProtocol, AIModelDefinition]]:
        policy = self.policy(task_type)
        routes: list[tuple[AIProviderProtocol, AIModelDefinition]] = []
        for model_id in policy.model_order:
            model = self._models[model_id]
            provider = self._providers[model.provider_id]
            if not model.enabled or not provider.definition.enabled:
                continue
            if not policy.required_capabilities <= model.capabilities:
                continue
            if provider.definition.external and not policy.allow_external:
                continue
            routes.append((provider, model))
        if not routes:
            raise AIRegistryError(f"No enabled model route satisfies {task_type}")
        return routes

    def embedding_routes(self) -> list[tuple[AIProviderProtocol, AIModelDefinition]]:
        return [
            route
            for route in self.routes(AITaskType.EMBEDDING)
            if AICapability.EMBEDDING in route[1].capabilities
        ]

    def _validate(self) -> None:
        for model in self._models.values():
            if model.provider_id not in self._providers:
                raise AIRegistryError(
                    f"Model {model.id} references missing provider {model.provider_id}"
                )
        for policy in self._policies.values():
            missing = [model_id for model_id in policy.model_order if model_id not in self._models]
            if missing:
                raise AIRegistryError(
                    f"Policy {policy.task_type} references missing models: {', '.join(missing)}"
                )
