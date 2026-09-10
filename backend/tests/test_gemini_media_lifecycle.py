from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest

from job_apply_pro.ai.providers import (
    AIProviderError,
    AIProviderMediaRetentionError,
    AIProviderRuntime,
    AIProviderUnavailableError,
    GeminiProvider,
)
from job_apply_pro.domain.ai import AIInputPart, AIProviderRequest

_HOST = "https://generativelanguage.googleapis.com"
_UPLOAD_URL = f"{_HOST}/upload/v1beta/files?upload_id=synthetic-session"


def _file(name: str = "files/synthetic-image") -> dict[str, object]:
    return {
        "file": {
            "name": name,
            "uri": f"{_HOST}/v1beta/{name}",
            "mimeType": "image/png",
            "state": "ACTIVE",
        }
    }


def _request(count: int = 1) -> AIProviderRequest:
    return AIProviderRequest(
        model="gemini-fixture",
        system_instruction="Review the synthetic image",
        user_content="Describe",
        input_parts=[
            AIInputPart(kind="media", data=b"\x89PNG\r\n\x1a\nfixture", mime_type="image/png")
            for _ in range(count)
        ],
        media_upload_consent=True,
        timeout_seconds=5,
    )


class _TrackedStream(httpx.SyncByteStream):
    def __init__(self, *, oversized: bool = False, broken: bool = False) -> None:
        self.oversized = oversized
        self.broken = broken
        self.read_chunks = 0
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        if self.broken:
            raise httpx.ReadError("synthetic response interruption")
        for _ in range(100 if self.oversized else 1):
            self.read_chunks += 1
            yield b" " * (64 * 1024)

    def close(self) -> None:
        self.closed = True


class _Harness:
    def __init__(self, uploads: list[object] | None = None) -> None:
        self.uploads = [_file()] if uploads is None else uploads
        self.events: list[str] = []
        self.start: httpx.Response | None = None
        self.deletions: dict[str, httpx.Response] = {}
        self.interaction = httpx.Response(
            200,
            json={
                "status": "completed",
                "steps": [
                    {"type": "model_output", "content": [{"type": "text", "text": "Reviewed"}]}
                ],
            },
        )
        self.provider = GeminiProvider(
            AIProviderRuntime.model_validate(
                {
                    "definition": {
                        "id": "gemini",
                        "kind": "GEMINI",
                        "base_url": f"{_HOST}/v1beta",
                        "external": True,
                    },
                    "api_key": "synthetic-test-key",
                }
            ),
            transport=httpx.MockTransport(self.handle),
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            name = request.url.path.removeprefix("/v1beta/")
            self.events.append(f"delete:{name}")
            return self.deletions.get(name, httpx.Response(204))
        command = request.headers.get("x-goog-upload-command")
        if command == "start":
            self.events.append("start")
            return self.start or httpx.Response(200, headers={"x-goog-upload-url": _UPLOAD_URL})
        if command == "upload, finalize":
            self.events.append("upload")
            reply = self.uploads.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)
        assert request.url.path == "/v1beta/interactions"
        self.events.append("interaction")
        return self.interaction


def test_multiple_uploads_are_deleted_in_reverse_order() -> None:
    harness = _Harness([_file("files/first"), _file("files/second")])
    assert harness.provider.complete(_request(2)).content == "Reviewed"
    assert harness.events == [
        "start",
        "upload",
        "start",
        "upload",
        "interaction",
        "delete:files/second",
        "delete:files/first",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("uri", None),
        ("uri", 123),
        ("uri", f"{_HOST}:invalid/v1beta/files/synthetic-image"),
        ("uri", f"{_HOST}/v1beta/files/another-image"),
        ("uri", f"{_HOST}/v1beta/files/synthetic-image?extra=true"),
        ("uri", f"{_HOST}/v1beta/files/synthetic-image#fragment"),
        ("uri", f"{_HOST}/v1beta/files/synthetic-image?"),
        ("uri", f"{_HOST}/v1beta/files/synthetic-image#"),
        ("uri", f"{_HOST}/v1beta/files/synthetic-image;parameter"),
        ("uri", f"{_HOST}/v1beta/files/synthetic-image\n"),
        ("uri", "https://:password@generativelanguage.googleapis.com/v1beta/files/synthetic-image"),
        ("uri", "https://[invalid/v1beta/files/synthetic-image"),
        ("mimeType", None),
        ("mimeType", "image/jpeg"),
        ("state", None),
        ("state", "PROCESSING"),
        ("state", "FAILED"),
        ("state", {"name": "ACTIVE"}),
    ],
)
def test_known_resource_is_deleted_before_invalid_metadata_fails(field: str, value: object) -> None:
    payload = _file()
    metadata = payload["file"]
    assert isinstance(metadata, dict)
    if value is None:
        del metadata[field]
    else:
        metadata[field] = value
    harness = _Harness([payload])
    with pytest.raises(AIProviderError) as caught:
        harness.provider.complete(_request())
    assert type(caught.value) is AIProviderError
    assert harness.events == ["start", "upload", "delete:files/synthetic-image"]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"file": None},
        {"file": []},
        {"file": {}},
        {"file": {"name": 123}},
        {"file": {"name": "files/../unexpected"}},
    ],
)
def test_unknown_finalized_resource_stops_with_retention_failure(payload: object) -> None:
    harness = _Harness([_file("files/first"), payload])
    with pytest.raises(AIProviderMediaRetentionError):
        harness.provider.complete(_request(2))
    assert harness.events == ["start", "upload", "start", "upload", "delete:files/first"]


def test_deeply_nested_interaction_fails_safely_and_deletes_known_media() -> None:
    harness = _Harness()
    harness.interaction = httpx.Response(200, content=b"[" * 20_000 + b"]" * 20_000)
    with pytest.raises(AIProviderError, match="JSON nesting limit"):
        harness.provider.complete(_request())
    assert harness.events[-1] == "delete:files/synthetic-image"


def test_cleanup_failure_does_not_skip_other_uploaded_resources() -> None:
    harness = _Harness([_file("files/first"), _file("files/second")])
    harness.deletions["files/second"] = httpx.Response(503)
    harness.deletions["files/first"] = httpx.Response(500)
    with pytest.raises(AIProviderMediaRetentionError, match="deletion could not be confirmed"):
        harness.provider.complete(_request(2))
    assert harness.events[-3:] == ["interaction", "delete:files/second", "delete:files/first"]


def test_invalid_metadata_and_failed_cleanup_is_terminal_retention_failure() -> None:
    harness = _Harness([{"file": {"name": "files/synthetic-image"}}])
    harness.deletions["files/synthetic-image"] = httpx.Response(500)
    with pytest.raises(AIProviderMediaRetentionError):
        harness.provider.complete(_request())
    assert "interaction" not in harness.events


def test_already_deleted_resource_is_success_without_consuming_error_body() -> None:
    harness = _Harness()
    body = _TrackedStream(broken=True)
    harness.deletions["files/synthetic-image"] = httpx.Response(404, stream=body)
    assert harness.provider.complete(_request()).content == "Reviewed"
    assert body.closed and body.read_chunks == 0


@pytest.mark.parametrize(
    "failure", ["http", "redirect", "json", "deep_json", "stream", "oversized", "timeout"]
)
def test_unknown_finalization_response_never_becomes_retryable(failure: str) -> None:
    reply: object
    body: _TrackedStream | None = None
    if failure == "http":
        reply = httpx.Response(500)
    elif failure == "redirect":
        reply = httpx.Response(307, headers={"location": "https://attacker.invalid/upload"})
    elif failure == "json":
        reply = httpx.Response(200, content=b"not-json")
    elif failure == "deep_json":
        reply = httpx.Response(200, content=b"[" * 20_000 + b"]" * 20_000)
    elif failure == "timeout":
        reply = httpx.ReadTimeout("synthetic finalization timeout")
    else:
        body = _TrackedStream(oversized=failure == "oversized", broken=failure == "stream")
        reply = httpx.Response(200, stream=body)
    harness = _Harness([reply])
    with pytest.raises(AIProviderMediaRetentionError, match="finalization outcome"):
        harness.provider.complete(_request())
    assert harness.events == ["start", "upload"]
    if body is not None:
        assert body.closed
        assert body.read_chunks <= 81


@pytest.mark.parametrize("stage", ["start", "delete"])
@pytest.mark.parametrize("failure", ["oversized", "stream"])
def test_start_and_delete_responses_are_streamed_and_bounded(stage: str, failure: str) -> None:
    harness = _Harness()
    body = _TrackedStream(oversized=failure == "oversized", broken=failure == "stream")
    response = httpx.Response(200, headers={"x-goog-upload-url": _UPLOAD_URL}, stream=body)
    if stage == "start":
        harness.start = response
    else:
        harness.deletions["files/synthetic-image"] = response
    with pytest.raises(AIProviderError) as caught:
        harness.provider.complete(_request())
    assert isinstance(caught.value, AIProviderMediaRetentionError) is (stage == "delete")
    assert body.closed and body.read_chunks <= 81
    if stage == "start":
        assert harness.events == ["start"]


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.invalid/upload/v1beta/files",
        f"{_HOST}/upload/../v1beta/files",
        f"{_HOST}/upload/v1beta/files/other",
        f"{_HOST}/upload/v1beta/files#fragment",
        f"{_HOST}/upload/v1beta/files#",
        f"{_HOST}/upload/v1beta/files;parameter",
        f"{_HOST}/upload/v1beta/files\t",
        f"{_HOST}:invalid/upload/v1beta/files",
        "https://user:password@generativelanguage.googleapis.com/upload/v1beta/files",
        "https://[invalid/upload/v1beta/files",
    ],
)
def test_untrusted_upload_session_is_rejected_before_any_bytes_are_sent(url: str) -> None:
    harness = _Harness()
    harness.start = httpx.Response(200, headers={"x-goog-upload-url": url})
    with pytest.raises(AIProviderError, match="untrusted upload URL"):
        harness.provider.complete(_request())
    assert harness.events == ["start"]


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "completed", "steps": {}},
        {"status": "completed", "steps": [None]},
        {"status": "completed", "steps": [{"type": "model_output", "content": "bad"}]},
        {"status": "completed", "steps": [{"type": "model_output", "content": [None]}]},
        {
            "status": "completed",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": "Reviewed"}]}],
            "usage": None,
        },
    ],
)
def test_malformed_interaction_envelope_is_sanitized_and_media_is_deleted(
    payload: dict[str, object],
) -> None:
    harness = _Harness()
    harness.interaction = httpx.Response(200, json=payload)
    with pytest.raises(AIProviderError, match="invalid interaction envelope"):
        harness.provider.complete(_request())
    assert harness.events[-1] == "delete:files/synthetic-image"


def test_interaction_failure_stays_retryable_only_after_confirmed_cleanup() -> None:
    harness = _Harness()
    harness.interaction = httpx.Response(503)
    with pytest.raises(AIProviderUnavailableError):
        harness.provider.complete(_request())
    assert harness.events[-1] == "delete:files/synthetic-image"


@pytest.mark.parametrize("tokens", ["12", -1, True, float("inf"), float("nan"), [], None])
def test_invalid_interaction_token_counts_are_sanitized_and_media_is_deleted(
    tokens: object,
) -> None:
    harness = _Harness()
    payload = json.dumps(
        {
            "status": "completed",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": "Reviewed"}]}],
            "usage": {"total_input_tokens": tokens},
        }
    )
    harness.interaction = httpx.Response(200, content=payload)
    with pytest.raises(AIProviderError, match="invalid interaction envelope"):
        harness.provider.complete(_request())
    assert harness.events[-1] == "delete:files/synthetic-image"
