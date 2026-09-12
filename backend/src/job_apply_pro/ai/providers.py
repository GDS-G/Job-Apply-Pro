from __future__ import annotations

import json
import math
import re
import sys
import time
from collections.abc import Callable
from typing import Protocol, cast
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from job_apply_pro.ai.media_journal import MediaJournal
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


class AIProviderMediaRetentionError(AIProviderError):
    """Remote media retention is unresolved; do not retry or use another route."""


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
                elif part.kind == "image_url":
                    user_content.append({"type": "image_url", "image_url": {"url": part.value}})
                else:
                    raise AIProviderError(
                        "OpenAI-compatible media bytes require a provider-specific upload adapter"
                    )
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
    _MAX_MEDIA_BYTES = 5 * 1024 * 1024
    _MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
    _FILE_NAME_PATTERN = re.compile(r"^files/[a-z0-9-]{1,40}$")

    def __init__(
        self,
        runtime: AIProviderRuntime,
        *,
        transport: httpx.BaseTransport | None = None,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
        journal_factory: Callable[[], MediaJournal] | None = None,
    ) -> None:
        self.definition = runtime.definition
        self._api_key = runtime.api_key
        self._transport = transport
        self._client_factory = client_factory
        self._journal_factory = journal_factory
        self._validate_runtime()

    def complete(self, request: AIProviderRequest) -> AIProviderResponse:
        input_blocks: list[dict[str, object]] = [{"type": "text", "text": request.user_content}]
        journal: MediaJournal | None = None
        model_name = self._model_name(request.model)
        try:
            for part in request.input_parts:
                if part.kind == "text":
                    input_blocks.append({"type": "text", "text": part.value})
                elif part.kind == "image_url":
                    raise AIProviderError("Gemini does not fetch user-supplied media URLs")
                else:
                    if not request.media_upload_consent:
                        raise AIProviderError("Gemini media upload requires explicit consent")
                    if journal is None:
                        if self._journal_factory is None:
                            raise AIProviderMediaRetentionError(
                                "Gemini media requires durable cleanup storage"
                            )
                        journal = self._journal_factory()
                    uri = self._upload_media(
                        cast(bytes, part.data),
                        cast(str, part.mime_type),
                        part.display_name or "Job Apply Pro review image",
                        request.timeout_seconds,
                        journal,
                    )
                    input_blocks.append({"type": "image", "uri": uri, "mime_type": part.mime_type})

            payload: dict[str, object] = {
                "model": model_name,
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

            if journal is not None:
                journal.renew()
            response = self._post("interactions", payload, request.timeout_seconds)
            if journal is not None:
                journal.renew()
            status = cast(str, response["status"])
            if status not in {"completed", "requires_action"}:
                raise AIProviderError("Gemini interaction did not complete")
            steps = response["steps"]
            if not isinstance(steps, list):
                raise TypeError("interaction steps are invalid")
            content_parts: list[str] = []
            tool_calls: list[AIToolCall] = []
            for step in steps:
                if not isinstance(step, dict):
                    raise TypeError("interaction step is invalid")
                step_type = step.get("type")
                if step_type == "model_output":
                    blocks = step.get("content", [])
                    if not isinstance(blocks, list):
                        raise TypeError("model content is invalid")
                    for block in blocks:
                        if not isinstance(block, dict):
                            raise TypeError("model content block is invalid")
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
            usage = response.get("usage", {})
            if not isinstance(usage, dict):
                raise TypeError("interaction usage is invalid")
            input_tokens = usage.get("total_input_tokens", 0)
            output_tokens = usage.get("total_output_tokens", 0)
            if any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in (input_tokens, output_tokens)
            ):
                raise TypeError("interaction token usage is invalid")
            result = AIProviderResponse(
                content="".join(content_parts),
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except AIProviderError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise AIProviderError("Gemini returned an invalid interaction envelope") from error
        finally:
            if journal is not None:
                active_error = sys.exception()
                try:
                    journal.cleanup(lambda name: self._delete_media(name, request.timeout_seconds))
                except AIProviderMediaRetentionError:
                    if isinstance(active_error, AIProviderMediaRetentionError):
                        raise active_error from None
                    raise
        return result

    def _upload_media(
        self,
        data: bytes,
        mime_type: str,
        display_name: str,
        timeout: float,
        journal: MediaJournal,
    ) -> str:
        if not data or len(data) > self._MAX_MEDIA_BYTES:
            raise AIProviderError("Gemini media exceeds the 5 MiB upload limit")
        journal.renew()
        record_id = journal.begin()
        transfer_started = False
        deadline = time.monotonic() + timeout
        base = str(self.definition.base_url).rstrip("/").removesuffix("/v1beta")
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(data)),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "X-Goog-Upload-Protocol": "resumable",
            "x-goog-api-key": cast(SecretStr, self._api_key).get_secret_value(),
        }
        try:
            with self._client_factory(
                timeout=timeout, transport=self._transport, follow_redirects=False
            ) as client:
                with client.stream(
                    "POST",
                    f"{base}/upload/v1beta/files",
                    headers=headers,
                    json={"file": {"display_name": display_name}},
                ) as start:
                    self._read_response_body(start, deadline=deadline)
                    upload_url = start.headers.get("x-goog-upload-url", "")
                    self._validate_upload_url(upload_url)
                try:
                    journal.renew()
                    transfer_started = True
                    deadline = time.monotonic() + timeout
                    with client.stream(
                        "POST",
                        upload_url,
                        headers={
                            "Content-Length": str(len(data)),
                            "Content-Type": mime_type,
                            "X-Goog-Upload-Command": "upload, finalize",
                            "X-Goog-Upload-Offset": "0",
                        },
                        content=data,
                    ) as uploaded:
                        payload = json.loads(self._read_response_body(uploaded, deadline=deadline))
                except (httpx.HTTPError, ValueError, RecursionError, AIProviderError) as error:
                    # The server may have finalized the upload before the response failed.
                    # Without a validated resource name, immediate deletion is impossible.
                    raise AIProviderMediaRetentionError(
                        "Gemini media finalization outcome could not be confirmed"
                    ) from error
        except AIProviderError:
            if not transfer_started:
                journal.abandon_before_upload(record_id)
            raise
        except (httpx.HTTPError, ValueError) as error:
            if not transfer_started:
                journal.abandon_before_upload(record_id)
            raise AIProviderUnavailableError("Gemini media upload failed") from error
        file = payload.get("file") if isinstance(payload, dict) else None
        name = file.get("name") if isinstance(file, dict) else None
        if not isinstance(name, str) or not self._FILE_NAME_PATTERN.fullmatch(name):
            raise AIProviderMediaRetentionError(
                "Gemini uploaded media resource could not be identified for deletion"
            )
        # Register ownership before inspecting any other untrusted metadata. Even a
        # missing URI, invalid port, or failed processing state must reach cleanup.
        journal.register(record_id, name)
        assert isinstance(file, dict)
        uri = file.get("uri")
        if (
            not isinstance(uri, str)
            or file.get("mimeType") != mime_type
            or file.get("state") != "ACTIVE"
        ):
            raise AIProviderError("Gemini returned invalid uploaded-file metadata")
        try:
            parsed = urlparse(uri)
            trusted = (
                parsed.scheme == "https"
                and parsed.hostname == self._API_HOST
                and parsed.port in {None, 443}
                and parsed.username is None
                and parsed.password is None
                and parsed.path == f"/v1beta/{name}"
                and not parsed.params
                and not parsed.query
                and not parsed.fragment
                and "?" not in uri
                and "#" not in uri
                and not any(ord(character) <= 32 for character in uri)
            )
        except ValueError as error:
            raise AIProviderError("Gemini returned an untrusted uploaded-file URI") from error
        if not trusted:
            raise AIProviderError("Gemini returned an untrusted uploaded-file URI")
        return uri

    def delete_uploaded_media(self, name: str, timeout: float) -> None:
        """Recovery entrypoint: delete a validated known resource, never upload."""
        self._delete_media(name, timeout)

    def _delete_media(self, name: str, timeout: float) -> None:
        if not self._FILE_NAME_PATTERN.fullmatch(name):
            raise AIProviderError("Gemini file name is invalid")
        url = f"{str(self.definition.base_url).rstrip('/')}/{name}"
        try:
            with (
                self._client_factory(
                    timeout=timeout, transport=self._transport, follow_redirects=False
                ) as client,
                client.stream(
                    "DELETE",
                    url,
                    headers={"x-goog-api-key": cast(SecretStr, self._api_key).get_secret_value()},
                ) as response,
            ):
                response.raise_for_status() if response.status_code != 404 else None
                if response.status_code not in {200, 204, 404}:
                    raise AIProviderMediaRetentionError("Gemini deletion is not confirmed")
                # A successful DELETE's body is irrelevant; never let a streaming
                # body hold the recovery worker/shutdown indefinitely. 202 is NOT
                # evidence of completed deletion.
        except httpx.HTTPError as error:
            raise AIProviderUnavailableError("Gemini media deletion failed") from error

    @classmethod
    def _validate_upload_url(cls, value: str) -> None:
        try:
            parsed = urlparse(value)
            trusted = (
                parsed.scheme == "https"
                and parsed.hostname == cls._API_HOST
                and parsed.port in {None, 443}
                and parsed.username is None
                and parsed.password is None
                and parsed.path == "/upload/v1beta/files"
                and not parsed.params
                and not parsed.fragment
                and "#" not in value
                and not any(ord(character) <= 32 for character in value)
            )
        except ValueError as error:
            raise AIProviderError("Gemini returned an untrusted upload URL") from error
        if not trusted:
            raise AIProviderError("Gemini returned an untrusted upload URL")

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
        deadline = time.monotonic() + timeout
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
                body = self._read_response_body(response, deadline=deadline)
            try:
                result = json.loads(body)
            except RecursionError as error:
                raise AIProviderError("Gemini response exceeded the JSON nesting limit") from error
        except AIProviderError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise AIProviderUnavailableError(
                f"Provider {self.definition.id} request failed"
            ) from error
        if not isinstance(result, dict):
            raise AIProviderError("Gemini returned a non-object response")
        return result

    @classmethod
    def _read_response_body(cls, response: httpx.Response, *, deadline: float) -> bytes:
        response.raise_for_status()
        body = bytearray()
        if time.monotonic() >= deadline:
            raise AIProviderError("Gemini response exceeded the time limit")
        for chunk in response.iter_bytes():
            if time.monotonic() >= deadline:
                raise AIProviderError("Gemini response exceeded the time limit")
            if len(body) + len(chunk) > cls._MAX_RESPONSE_BYTES:
                raise AIProviderError("Gemini response exceeded the size limit")
            body.extend(chunk)
        if time.monotonic() >= deadline:
            raise AIProviderError("Gemini response exceeded the time limit")
        return bytes(body)

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
