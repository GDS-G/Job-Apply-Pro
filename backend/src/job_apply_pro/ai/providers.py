from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from job_apply_pro.domain.ai import (
    AIProviderDefinition,
    AIProviderRequest,
    AIProviderResponse,
    AIToolCall,
)


class AIProviderError(RuntimeError):
    pass


class AIProviderUnavailableError(AIProviderError):
    pass


class AIProviderProtocol(Protocol):
    definition: AIProviderDefinition

    def complete(self, request: AIProviderRequest) -> AIProviderResponse: ...

    def embed(self, model: str, texts: list[str], timeout_seconds: float) -> list[list[float]]: ...


class AIProviderRuntime(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    definition: AIProviderDefinition
    api_key: SecretStr | None = None


class OpenAICompatibleProvider:
    """Narrow adapter for OpenAI-compatible cloud and llama.cpp HTTP APIs."""

    def __init__(
        self,
        runtime: AIProviderRuntime,
        *,
        transport: httpx.BaseTransport | None = None,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ) -> None:
        self.definition = runtime.definition
        self._api_key = runtime.api_key
        self._transport = transport
        self._client_factory = client_factory
        self._validate_endpoint()

    def complete(self, request: AIProviderRequest) -> AIProviderResponse:
        user_content: str | list[dict[str, object]] = request.user_content
        if request.input_parts:
            user_content = [{"type": "text", "text": request.user_content}]
            for part in request.input_parts:
                if part.kind == "text":
                    user_content.append({"type": "text", "text": part.value})
                else:
                    user_content.append({"type": "image_url", "image_url": {"url": part.value}})
        payload: dict[str, object] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_instruction},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in request.tools
            ]
        if request.output_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "job_apply_pro_response",
                    "strict": True,
                    "schema": request.output_schema,
                },
            }
        response = self._post("chat/completions", payload, request.timeout_seconds)
        try:
            choices = cast(list[dict[str, object]], response["choices"])
            message = cast(dict[str, object], choices[0]["message"])
            content = message.get("content") or ""
            usage = cast(dict[str, object], response.get("usage", {}))
            if not isinstance(content, str):
                raise TypeError("content is not text")
            tool_calls = self._tool_calls(message.get("tool_calls", []))
            return AIProviderResponse(
                content=content,
                tool_calls=tool_calls,
                input_tokens=int(cast(int, usage.get("prompt_tokens", 0))),
                output_tokens=int(cast(int, usage.get("completion_tokens", 0))),
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise AIProviderError("Provider returned an invalid completion envelope") from error

    def embed(self, model: str, texts: list[str], timeout_seconds: float) -> list[list[float]]:
        response = self._post(
            "embeddings",
            {"model": model, "input": texts, "encoding_format": "float"},
            timeout_seconds,
        )
        try:
            data = cast(list[dict[str, object]], response["data"])
            rows = sorted(data, key=lambda item: int(cast(int, item["index"])))
            vectors = [
                [float(value) for value in cast(list[float], row["embedding"])] for row in rows
            ]
        except (KeyError, TypeError, ValueError) as error:
            raise AIProviderError("Provider returned an invalid embedding envelope") from error
        if len(vectors) != len(texts) or any(not vector for vector in vectors):
            raise AIProviderError("Provider returned incomplete embeddings")
        return vectors

    def _post(self, path: str, payload: dict[str, object], timeout: float) -> dict[str, object]:
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key.get_secret_value()}"
        url = f"{str(self.definition.base_url).rstrip('/')}/{path}"
        try:
            with self._client_factory(
                timeout=timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise AIProviderUnavailableError(
                f"Provider {self.definition.id} request failed"
            ) from error
        if not isinstance(result, dict):
            raise AIProviderError("Provider returned a non-object response")
        return result

    @staticmethod
    def _tool_calls(value: object) -> list[AIToolCall]:
        rows = cast(list[dict[str, object]], value)
        calls: list[AIToolCall] = []
        for row in rows:
            function = cast(dict[str, object], row["function"])
            arguments = json.loads(cast(str, function["arguments"]))
            if not isinstance(arguments, dict):
                raise AIProviderError("Tool arguments must be a JSON object")
            calls.append(
                AIToolCall(
                    id=cast(str, row["id"]),
                    name=cast(str, function["name"]),
                    arguments=arguments,
                )
            )
        return calls

    def _validate_endpoint(self) -> None:
        url = self.definition.base_url
        host = (url.host or "").casefold()
        if self.definition.external and url.scheme != "https":
            raise ValueError("External AI providers require HTTPS")
        if not self.definition.external and host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Local AI providers must use a loopback endpoint")
