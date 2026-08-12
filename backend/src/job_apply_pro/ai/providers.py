from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from typing import Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from job_apply_pro.domain.ai import (
    AIProviderDefinition,
    AIProviderRequest,
    AIProviderResponse,
    AIToolCall,
    ProviderKind,
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


class GeminiProvider:
    """Stateless native adapter for Google's Gemini Interactions and embedding APIs."""

    _API_HOST = "generativelanguage.googleapis.com"
    _API_PATH = "/v1beta"
    _API_REVISION = "2026-05-20"
    _MAX_RESPONSE_BYTES = 5 * 1024 * 1024
    _MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,160}$")

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
        self._validate_runtime()

    def complete(self, request: AIProviderRequest) -> AIProviderResponse:
        input_blocks: list[dict[str, object]] = [{"type": "text", "text": request.user_content}]
        for part in request.input_parts:
            if part.kind == "text":
                input_blocks.append({"type": "text", "text": part.value})
            else:
                raise AIProviderError(
                    "Gemini image URLs require a separately uploaded trusted file and MIME type"
                )

        payload: dict[str, object] = {
            "model": self._model_name(request.model),
            "input": input_blocks,
            "system_instruction": request.system_instruction,
            "store": False,
            "generation_config": {"temperature": 0},
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                }
                for tool in request.tools
            ]
        if request.output_schema is not None:
            payload["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": request.output_schema,
            }

        response = self._post("interactions", payload, request.timeout_seconds)
        try:
            status = cast(str, response["status"])
            if status not in {"completed", "requires_action"}:
                raise AIProviderError("Gemini interaction did not complete")
            steps = cast(list[dict[str, object]], response["steps"])
            content_parts: list[str] = []
            tool_calls: list[AIToolCall] = []
            for step in steps:
                step_type = step.get("type")
                if step_type == "model_output":
                    blocks = cast(list[dict[str, object]], step.get("content", []))
                    for block in blocks:
                        if block.get("type") == "text":
                            text = block.get("text")
                            if not isinstance(text, str):
                                raise TypeError("model text is invalid")
                            content_parts.append(text)
                elif step_type == "function_call":
                    arguments = step.get("arguments")
                    if not isinstance(arguments, dict):
                        raise TypeError("function arguments are invalid")
                    tool_calls.append(
                        AIToolCall(
                            id=cast(str, step["id"]),
                            name=cast(str, step["name"]),
                            arguments=arguments,
                        )
                    )
            if not content_parts and not tool_calls:
                raise AIProviderError("Gemini returned no usable output")
            usage = cast(dict[str, object], response.get("usage", {}))
            return AIProviderResponse(
                content="".join(content_parts),
                tool_calls=tool_calls,
                input_tokens=int(cast(int, usage.get("total_input_tokens", 0))),
                output_tokens=int(cast(int, usage.get("total_output_tokens", 0))),
            )
        except AIProviderError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise AIProviderError("Gemini returned an invalid interaction envelope") from error

    def embed(self, model: str, texts: list[str], timeout_seconds: float) -> list[list[float]]:
        model_name = self._model_name(model)
        resource = f"models/{model_name}"
        response = self._post(
            f"models/{model_name}:batchEmbedContents",
            {
                "requests": [
                    {"model": resource, "content": {"parts": [{"text": text}]}} for text in texts
                ]
            },
            timeout_seconds,
        )
        try:
            embeddings = cast(list[dict[str, object]], response["embeddings"])
            vectors = [
                [float(value) for value in cast(list[float], embedding["values"])]
                for embedding in embeddings
            ]
        except (KeyError, TypeError, ValueError) as error:
            raise AIProviderError("Gemini returned an invalid embedding envelope") from error
        if (
            len(vectors) != len(texts)
            or any(not vector for vector in vectors)
            or len({len(vector) for vector in vectors}) > 1
            or any(not math.isfinite(value) for vector in vectors for value in vector)
        ):
            raise AIProviderError("Gemini returned incomplete embeddings")
        return vectors

    def _post(self, path: str, payload: dict[str, object], timeout: float) -> dict[str, object]:
        url = f"{str(self.definition.base_url).rstrip('/')}/{path}"
        headers = {
            "Api-Revision": self._API_REVISION,
            "Content-Type": "application/json",
            "x-goog-api-key": cast(SecretStr, self._api_key).get_secret_value(),
        }
        try:
            with (
                self._client_factory(
                    timeout=timeout,
                    transport=self._transport,
                    follow_redirects=False,
                ) as client,
                client.stream("POST", url, headers=headers, json=payload) as response,
            ):
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self._MAX_RESPONSE_BYTES:
                        raise AIProviderError("Gemini response exceeded the size limit")
            result = json.loads(body)
        except AIProviderError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise AIProviderUnavailableError(
                f"Provider {self.definition.id} request failed"
            ) from error
        if not isinstance(result, dict):
            raise AIProviderError("Gemini returned a non-object response")
        return result

    def _validate_runtime(self) -> None:
        url = self.definition.base_url
        if self.definition.kind is not ProviderKind.GEMINI:
            raise ValueError("Gemini adapter requires the GEMINI provider kind")
        if not self.definition.external:
            raise ValueError("Gemini is an external provider")
        if (
            url.scheme != "https"
            or (url.host or "").casefold() != self._API_HOST
            or url.port != 443
            or (url.path or "").rstrip("/") != self._API_PATH
            or url.query is not None
            or url.fragment is not None
            or url.username is not None
            or url.password is not None
        ):
            raise ValueError(
                "Gemini base URL must be https://generativelanguage.googleapis.com/v1beta"
            )
        if self._api_key is None or not self._api_key.get_secret_value().strip():
            raise ValueError("Gemini requires an API key")

    @classmethod
    def _model_name(cls, model: str) -> str:
        name = model.removeprefix("models/")
        if not cls._MODEL_PATTERN.fullmatch(name):
            raise AIProviderError("Gemini model name is invalid")
        return name
