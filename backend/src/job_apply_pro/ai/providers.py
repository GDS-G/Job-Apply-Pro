from __future__ import annotations

import json
import math
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
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


class AIProviderNotAppliedError(AIProviderError):
    """Local pre-dispatch validation proves no provider request was sent."""


class AIProviderRejectedError(AIProviderError):
    """The provider returned an explicit HTTP rejection."""


class AIProviderResponseError(AIProviderError):
    """A complete provider response was received but could not be used."""


class AIProviderUncertainError(AIProviderUnavailableError):
    """Dispatch began but a trustworthy provider response was not received."""


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
                    raise AIProviderNotAppliedError(
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
            raise AIProviderResponseError(
                "Provider returned an invalid completion envelope"
            ) from error

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
            raise AIProviderResponseError(
                "Provider returned an invalid embedding envelope"
            ) from error
        if len(vectors) != len(texts) or any(not vector for vector in vectors):
            raise AIProviderResponseError("Provider returned incomplete embeddings")
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
        except httpx.HTTPStatusError as error:
            raise AIProviderRejectedError(
                f"Provider {self.definition.id} rejected the request"
            ) from error
        except httpx.RequestError as error:
            raise AIProviderUncertainError(
                f"Provider {self.definition.id} response is uncertain"
            ) from error
        try:
            result = response.json()
        except (ValueError, RecursionError) as error:
            raise AIProviderResponseError(
                f"Provider {self.definition.id} returned invalid JSON"
            ) from error
        if not isinstance(result, dict):
            raise AIProviderResponseError("Provider returned a non-object response")
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


@dataclass
class _GeminiWorkBudget:
    deadline: float
    processing_gets: int = 0


class GeminiProvider:
    """Stateless native adapter for Google's Gemini Interactions and embedding APIs."""

    _API_HOST = "generativelanguage.googleapis.com"
    _API_PATH = "/v1beta"
    _API_REVISION = "2026-05-20"
    _MAX_RESPONSE_BYTES = 5 * 1024 * 1024
    _MAX_MEDIA_BYTES = 5 * 1024 * 1024
    _PROCESSING_POLL_SECONDS = 2.0
    _MAX_PROCESSING_GETS = 30
    _CLEANUP_BUDGET_SECONDS = 30.0
    _DELETE_TIMEOUT_SECONDS = 15.0
    _MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
    _FILE_NAME_PATTERN = re.compile(r"^files/[a-z0-9-]{1,40}$")

    def __init__(
        self,
        runtime: AIProviderRuntime,
        *,
        transport: httpx.BaseTransport | None = None,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
        journal_factory: Callable[[], MediaJournal] | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.definition = runtime.definition
        self._api_key = runtime.api_key
        self._transport = transport
        self._client_factory = client_factory
        self._journal_factory = journal_factory
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._validate_runtime()

    def complete(self, request: AIProviderRequest) -> AIProviderResponse:
        budget = _GeminiWorkBudget(self._clock() + request.timeout_seconds)
        input_blocks: list[dict[str, object]] = [{"type": "text", "text": request.user_content}]
        journal: MediaJournal | None = None
        model_name = self._model_name(request.model)
        try:
            for part in request.input_parts:
                if part.kind == "text":
                    input_blocks.append({"type": "text", "text": part.value})
                elif part.kind == "image_url":
                    raise AIProviderNotAppliedError(
                        "Gemini does not fetch user-supplied media URLs"
                    )
                else:
                    if not request.media_upload_consent:
                        raise AIProviderNotAppliedError(
                            "Gemini media upload requires explicit consent"
                        )
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
                        budget,
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
            response = self._post(
                "interactions", payload, request.timeout_seconds, deadline=budget.deadline
            )
            if journal is not None:
                journal.renew()
            self._remaining_work(budget.deadline)
            status = cast(str, response["status"])
            if status not in {"completed", "requires_action"}:
                raise AIProviderResponseError("Gemini interaction did not complete")
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
                raise AIProviderResponseError("Gemini returned no usable output")
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
            self._remaining_work(budget.deadline)
        except AIProviderError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise AIProviderResponseError(
                "Gemini returned an invalid interaction envelope"
            ) from error
        finally:
            if journal is not None:
                active_error = sys.exception()
                cleanup_deadline = self._clock() + self._CLEANUP_BUDGET_SECONDS

                def delete_with_budget(name: str) -> None:
                    self._delete_media(
                        name, self._DELETE_TIMEOUT_SECONDS, deadline=cleanup_deadline
                    )

                try:
                    # Always traverse the durable obligations, even when no network
                    # time remains: the journal must relinquish or preserve each one.
                    journal.cleanup(delete_with_budget)
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
        budget: _GeminiWorkBudget,
        journal: MediaJournal,
    ) -> str:
        if not data or len(data) > self._MAX_MEDIA_BYTES:
            raise AIProviderNotAppliedError("Gemini media exceeds the 5 MiB upload limit")
        journal.renew()
        self._remaining_work(budget.deadline)
        record_id = journal.begin()
        transfer_started = False
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
                timeout=self._remaining_work(budget.deadline),
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    "POST",
                    f"{base}/upload/v1beta/files",
                    headers=headers,
                    json={"file": {"display_name": display_name}},
                    timeout=self._remaining_work(budget.deadline),
                ) as start:
                    self._read_response_body(start, deadline=budget.deadline)
                    upload_url = start.headers.get("x-goog-upload-url", "")
                    self._validate_upload_url(upload_url)
                journal.renew()
                # Expiry here proves no media transfer began, so the durable intent
                # can be abandoned instead of being labeled an unknown upload.
                remaining = self._remaining_work(budget.deadline)
                try:
                    transfer_started = True
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
                        timeout=remaining,
                    ) as uploaded:
                        payload = json.loads(
                            self._read_response_body(uploaded, deadline=budget.deadline)
                        )
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
        return self._await_active_media(file, name, mime_type, budget, journal)

    def _await_active_media(
        self,
        file: dict[str, object],
        name: str,
        mime_type: str,
        budget: _GeminiWorkBudget,
        journal: MediaJournal,
    ) -> str:
        while True:
            self._remaining_work(budget.deadline)
            uri = self._validated_media_uri(file, name, mime_type)
            if uri is not None:
                return uri
            if budget.processing_gets >= self._MAX_PROCESSING_GETS:
                raise AIProviderError("Gemini media processing exceeded the polling limit")
            journal.renew()
            self._sleep(min(self._PROCESSING_POLL_SECONDS, self._remaining_work(budget.deadline)))
            journal.renew()
            self._remaining_work(budget.deadline)
            journal.renew()
            budget.processing_gets += 1
            try:
                file = self._get_media(name, budget.deadline)
            finally:
                journal.renew()

    def _validated_media_uri(
        self, file: dict[str, object], name: str, mime_type: str
    ) -> str | None:
        if file.get("name") != name or file.get("mimeType") != mime_type:
            raise AIProviderError("Gemini returned invalid uploaded-file metadata")
        state = file.get("state")
        if state == "PROCESSING":
            # Never follow a PROCESSING response's URI. Poll only the original
            # durably registered resource using the fixed Files API endpoint.
            return None
        if state == "FAILED":
            raise AIProviderError("Gemini media processing failed")
        uri = file.get("uri")
        if not isinstance(uri, str) or state != "ACTIVE":
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

    def _get_media(self, name: str, deadline: float) -> dict[str, object]:
        url = f"{str(self.definition.base_url).rstrip('/')}/{name}"
        try:
            with (
                self._client_factory(
                    timeout=self._remaining_work(deadline),
                    transport=self._transport,
                    follow_redirects=False,
                ) as client,
                client.stream(
                    "GET",
                    url,
                    headers={"x-goog-api-key": cast(SecretStr, self._api_key).get_secret_value()},
                    timeout=self._remaining_work(deadline),
                ) as response,
            ):
                result = json.loads(self._read_response_body(response, deadline=deadline))
        except AIProviderError:
            raise
        except (httpx.HTTPError, ValueError, RecursionError) as error:
            raise AIProviderUnavailableError(
                "Gemini media processing status request failed"
            ) from error
        if not isinstance(result, dict):
            raise AIProviderError("Gemini returned invalid processing metadata")
        return result

    def delete_uploaded_media(self, name: str, timeout: float) -> None:
        """Recovery entrypoint: delete a validated known resource, never upload."""
        self._delete_media(name, timeout)

    def _delete_media(self, name: str, timeout: float, *, deadline: float | None = None) -> None:
        if not self._FILE_NAME_PATTERN.fullmatch(name):
            raise AIProviderError("Gemini file name is invalid")
        url = f"{str(self.definition.base_url).rstrip('/')}/{name}"
        try:
            with (
                self._client_factory(
                    timeout=self._remaining_delete_timeout(timeout, deadline),
                    transport=self._transport,
                    follow_redirects=False,
                ) as client,
                client.stream(
                    "DELETE",
                    url,
                    headers={"x-goog-api-key": cast(SecretStr, self._api_key).get_secret_value()},
                    timeout=self._remaining_delete_timeout(timeout, deadline),
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

    def _remaining_delete_timeout(self, timeout: float, deadline: float | None) -> float:
        if deadline is None:
            return timeout
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise AIProviderMediaRetentionError("Gemini media cleanup time budget is exhausted")
        return min(timeout, remaining)

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
            raise AIProviderResponseError(
                "Gemini returned an invalid embedding envelope"
            ) from error
        if (
            len(vectors) != len(texts)
            or any(not vector for vector in vectors)
            or len({len(vector) for vector in vectors}) > 1
            or any(not math.isfinite(value) for vector in vectors for value in vector)
        ):
            raise AIProviderResponseError("Gemini returned incomplete embeddings")
        return vectors

    def _post(
        self,
        path: str,
        payload: dict[str, object],
        timeout: float,
        *,
        deadline: float | None = None,
    ) -> dict[str, object]:
        url = f"{str(self.definition.base_url).rstrip('/')}/{path}"
        if deadline is None:
            deadline = self._clock() + timeout
        headers = {
            "Api-Revision": self._API_REVISION,
            "Content-Type": "application/json",
            "x-goog-api-key": cast(SecretStr, self._api_key).get_secret_value(),
        }
        try:
            with (
                self._client_factory(
                    timeout=self._remaining_work(deadline),
                    transport=self._transport,
                    follow_redirects=False,
                ) as client,
                client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self._remaining_work(deadline),
                ) as response,
            ):
                body = self._read_response_body(response, deadline=deadline)
        except (AIProviderError, AIProviderMediaRetentionError):
            raise
        except httpx.HTTPStatusError as error:
            raise AIProviderRejectedError(
                f"Provider {self.definition.id} rejected the request"
            ) from error
        except (httpx.RequestError, ValueError) as error:
            raise AIProviderUncertainError(
                f"Provider {self.definition.id} response is uncertain"
            ) from error
        try:
            result = json.loads(body)
        except RecursionError as error:
            raise AIProviderResponseError(
                "Gemini response exceeded the JSON nesting limit"
            ) from error
        except ValueError as error:
            raise AIProviderResponseError("Gemini returned an invalid JSON response") from error
        if not isinstance(result, dict):
            raise AIProviderResponseError("Gemini returned a non-object response")
        return result

    def _remaining_work(self, deadline: float) -> float:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise AIProviderUncertainError("Gemini invocation exceeded the work time limit")
        return remaining

    def _read_response_body(self, response: httpx.Response, *, deadline: float) -> bytes:
        response.raise_for_status()
        body = bytearray()
        self._remaining_work(deadline)
        for chunk in response.iter_bytes():
            self._remaining_work(deadline)
            if len(body) + len(chunk) > self._MAX_RESPONSE_BYTES:
                raise AIProviderUncertainError("Gemini response exceeded the size limit")
            body.extend(chunk)
        self._remaining_work(deadline)
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
            raise AIProviderNotAppliedError("Gemini model name is invalid")
        return name
