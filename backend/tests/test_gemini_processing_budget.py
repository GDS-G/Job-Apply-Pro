from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from typing import cast

import httpx
import pytest

from image_helpers import synthetic_image_bytes
from job_apply_pro.ai.providers import (
    AIProviderError,
    AIProviderMediaRetentionError,
    AIProviderRuntime,
    GeminiProvider,
)
from job_apply_pro.domain.ai import AIInputPart, AIProviderRequest, AIProviderResponse
from job_apply_pro.domain.media_cleanup import MediaCleanupState
from media_cleanup_helpers import new_test_journal

_ORIGIN = "https://generativelanguage.googleapis.com"


def _metadata(state: str = "ACTIVE", name: str = "files/synthetic-image") -> dict[str, object]:
    return {
        "name": name,
        "uri": f"{_ORIGIN}/v1beta/{name}",
        "mimeType": "image/png",
        "state": state,
    }


def _request(count: int = 1, timeout: float = 20) -> AIProviderRequest:
    return AIProviderRequest(
        model="gemini-fixture",
        system_instruction="Review synthetic media",
        user_content="Describe",
        input_parts=[
            AIInputPart(kind="media", data=synthetic_image_bytes(), mime_type="image/png")
            for _ in range(count)
        ],
        media_upload_consent=True,
        timeout_seconds=timeout,
    )


class _Clock:
    def __init__(self, events: list[str]) -> None:
        self.now = 100.0
        self.events = events
        self.sleeps: list[float] = []
        self.oversleep = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.events.append("sleep")
        self.sleeps.append(seconds)
        self.now += seconds + self.oversleep


class _Journal:
    def __init__(self, events: list[str]) -> None:
        self.durable = new_test_journal()
        self.events = events
        self.renew_count = 0
        self.renew_effects: dict[int, Callable[[], None]] = {}

    def begin(self) -> str:
        self.events.append("begin")
        return self.durable.begin()

    def register(self, record_id: str, name: str) -> None:
        self.events.append(f"register:{name}")
        self.durable.register(record_id, name)

    def abandon_before_upload(self, record_id: str) -> None:
        self.events.append("abandon")
        self.durable.abandon_before_upload(record_id)

    def renew(self) -> None:
        self.events.append("renew")
        self.renew_count += 1
        if effect := self.renew_effects.get(self.renew_count):
            effect()
        self.durable.renew()

    def cleanup(self, delete: Callable[[str], None]) -> None:
        self.events.append("cleanup")

        def tracked_delete(name: str) -> None:
            self.events.append(f"obligation:{name}")
            delete(name)

        self.durable.cleanup(tracked_delete)


class _Harness:
    def __init__(
        self, uploads: Sequence[object] | None = None, gets: Sequence[object] | None = None
    ) -> None:
        self.events: list[str] = []
        self.clock = _Clock(self.events)
        self.journal = _Journal(self.events)
        self.uploads = deque(uploads if uploads is not None else [{"file": _metadata()}])
        self.gets = deque(gets or [])
        self.deletions: deque[object] = deque()
        self.latencies: dict[str, deque[float]] = {}
        self.requests: list[httpx.Request] = []
        self.provider = GeminiProvider(
            AIProviderRuntime.model_validate(
                {
                    "definition": {
                        "id": "gemini",
                        "kind": "GEMINI",
                        "base_url": f"{_ORIGIN}/v1beta",
                    },
                    "api_key": "synthetic-test-key",
                }
            ),
            transport=httpx.MockTransport(self.handle),
            journal_factory=lambda: self.journal,
            clock=self.clock,
            sleeper=self.clock.sleep,
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply: object
        if request.method == "GET":
            stage = "get"
            reply = self.gets.popleft()
        elif request.method == "DELETE":
            stage = "delete"
            reply = self.deletions.popleft() if self.deletions else httpx.Response(204)
        elif request.headers.get("x-goog-upload-command") == "start":
            stage = "start"
            reply = httpx.Response(
                200,
                headers={
                    "x-goog-upload-url": (
                        f"{_ORIGIN}/upload/v1beta/files?upload_id=synthetic-session"
                    )
                },
            )
        elif request.headers.get("x-goog-upload-command") == "upload, finalize":
            stage = "finalize"
            reply = self.uploads.popleft()
        else:
            assert request.url.path == "/v1beta/interactions"
            stage = "interaction"
            reply = {
                "status": "completed",
                "steps": [
                    {"type": "model_output", "content": [{"type": "text", "text": "Reviewed"}]}
                ],
            }
        self.events.append(stage)
        if latency := self.latencies.get(stage):
            self.clock.now += latency.popleft()
        if isinstance(reply, Exception):
            raise reply
        return (
            reply
            if isinstance(reply, httpx.Response)
            else httpx.Response(200, content=json.dumps(reply))
        )

    def methods(self) -> list[str]:
        return [request.method for request in self.requests]

    def timeouts(self) -> list[float]:
        return [
            cast(dict[str, float], request.extensions["timeout"])["read"]
            for request in self.requests
        ]


def test_processing_polls_original_resource_with_lease_renewals_before_use() -> None:
    initial = _metadata("PROCESSING")
    initial["uri"] = "https://attacker.invalid/never-follow"
    harness = _Harness([{"file": initial}], [_metadata("PROCESSING"), _metadata()])
    assert harness.provider.complete(_request()).content == "Reviewed"
    assert harness.methods() == ["POST", "POST", "GET", "GET", "POST", "DELETE"]
    assert harness.clock.sleeps == [2, 2]
    assert harness.events.index("register:files/synthetic-image") < harness.events.index("sleep")
    for index, event in enumerate(harness.events):
        if event in {"get", "sleep"}:
            assert harness.events[index - 1] == "renew"
            assert harness.events[index + 1] == "renew"
    for request in harness.requests:
        assert request.url.host == "generativelanguage.googleapis.com"
        if request.method == "GET":
            assert str(request.url) == f"{_ORIGIN}/v1beta/files/synthetic-image"
            assert request.content == b""
            assert request.headers["x-goog-api-key"] == "synthetic-test-key"
            assert "authorization" not in request.headers
    assert harness.events.index("interaction") > max(
        index for index, event in enumerate(harness.events) if event == "get"
    )


def test_active_upload_needs_no_poll_or_wait() -> None:
    harness = _Harness()
    assert harness.provider.complete(_request()).content == "Reviewed"
    assert harness.methods() == ["POST", "POST", "POST", "DELETE"]
    assert harness.clock.sleeps == []


@pytest.mark.parametrize("state", ["FAILED", "STATE_UNSPECIFIED", "unknown"])
def test_nonprocessing_upload_state_fails_after_durable_registration(state: str) -> None:
    harness = _Harness([{"file": _metadata(state)}])
    with pytest.raises(AIProviderError) as caught:
        harness.provider.complete(_request())
    assert not isinstance(caught.value, AIProviderMediaRetentionError)
    assert harness.methods() == ["POST", "POST", "DELETE"]
    assert harness.events.index("register:files/synthetic-image") < harness.events.index("cleanup")


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        [],
        {},
        {"file": _metadata()},
        _metadata("FAILED"),
        _metadata("STATE_UNSPECIFIED"),
        _metadata("ACTIVE", "files/another-image"),
        {**_metadata(), "uri": "https://attacker.invalid/private-token"},
        {**_metadata(), "mimeType": "image/jpeg"},
        {**_metadata(), "state": {"name": "ACTIVE"}},
    ],
)
def test_invalid_poll_metadata_never_changes_registered_cleanup_target(metadata: object) -> None:
    harness = _Harness([{"file": _metadata("PROCESSING")}], [metadata])
    with pytest.raises(AIProviderError) as caught:
        harness.provider.complete(_request())
    assert not isinstance(caught.value, AIProviderMediaRetentionError)
    assert "private-token" not in str(caught.value)
    assert harness.methods() == ["POST", "POST", "GET", "DELETE"]
    assert harness.requests[-1].url.path == "/v1beta/files/synthetic-image"
    assert [event for event in harness.events if event.startswith("register:")] == [
        "register:files/synthetic-image"
    ]


@pytest.mark.parametrize(
    "failure", ["404", "503", "redirect", "json", "deep_json", "oversized", "timeout"]
)
def test_failed_get_is_not_retried_and_still_deletes_known_media(failure: str) -> None:
    reply: object
    if failure.isdigit():
        reply = httpx.Response(int(failure))
    elif failure == "redirect":
        reply = httpx.Response(307, headers={"location": "https://attacker.invalid/private-token"})
    elif failure == "timeout":
        reply = httpx.ReadTimeout("private-token")
    else:
        content = {
            "json": b"private-token",
            "deep_json": b"[" * 20_000 + b"]" * 20_000,
            "oversized": b" " * (GeminiProvider._MAX_RESPONSE_BYTES + 1),
        }[failure]
        reply = httpx.Response(200, content=content)
    harness = _Harness([{"file": _metadata("PROCESSING")}], [reply])
    with pytest.raises(AIProviderError) as caught:
        harness.provider.complete(_request())
    assert not isinstance(caught.value, AIProviderMediaRetentionError)
    assert "private-token" not in str(caught.value)
    assert harness.methods() == ["POST", "POST", "GET", "DELETE"]


def test_work_budget_is_shared_by_upload_wait_get_and_interaction() -> None:
    harness = _Harness([{"file": _metadata("PROCESSING")}], [_metadata()])
    harness.latencies = {
        "start": deque([2]),
        "finalize": deque([2]),
        "get": deque([1]),
        "interaction": deque([2]),
    }
    assert harness.provider.complete(_request(timeout=10)).content == "Reviewed"
    assert harness.timeouts() == [10, 8, 4, 3, 15]


def test_work_budget_does_not_reset_for_later_images() -> None:
    harness = _Harness([{"file": _metadata(name=f"files/image-{index}")} for index in range(4)])
    harness.latencies = {"start": deque([1, 1, 1]), "finalize": deque([1, 1])}
    with pytest.raises(AIProviderError, match="work time limit") as caught:
        harness.provider.complete(_request(4, timeout=5))
    assert not isinstance(caught.value, AIProviderMediaRetentionError)
    assert harness.methods() == ["POST"] * 5 + ["DELETE"] * 2
    assert harness.events.count("abandon") == 1
    assert harness.timeouts() == [5, 4, 3, 2, 1, 15, 15]


def test_expiry_after_start_before_transfer_abandons_intent_without_retention_error() -> None:
    harness = _Harness()
    harness.journal.renew_effects[2] = lambda: setattr(harness.clock, "now", 120.0)
    with pytest.raises(AIProviderError, match="work time limit") as caught:
        harness.provider.complete(_request())
    assert not isinstance(caught.value, AIProviderMediaRetentionError)
    assert harness.methods() == ["POST"]
    assert "abandon" in harness.events and "finalize" not in harness.events
    assert not harness.journal.durable._repository.list_public()


def test_expiry_during_finalization_keeps_unknown_outcome_for_manual_review() -> None:
    harness = _Harness()
    harness.latencies = {"finalize": deque([20])}
    with pytest.raises(AIProviderMediaRetentionError, match="finalization outcome"):
        harness.provider.complete(_request())
    assert harness.methods() == ["POST", "POST"]
    records = harness.journal.durable._repository.list_public()
    assert len(records) == 1 and records[0].state is MediaCleanupState.MANUAL_REVIEW


@pytest.mark.parametrize("oversleep", [0.0, 10.0])
def test_wait_expiry_renews_lease_then_cleans_up_without_sending_get(oversleep: float) -> None:
    harness = _Harness([{"file": _metadata("PROCESSING")}])
    harness.clock.oversleep = oversleep
    with pytest.raises(AIProviderError, match="work time limit") as caught:
        harness.provider.complete(_request(timeout=1))
    assert not isinstance(caught.value, AIProviderMediaRetentionError)
    assert harness.clock.sleeps == [1]
    assert harness.events[harness.events.index("sleep") + 1] == "renew"
    assert harness.methods() == ["POST", "POST", "DELETE"]
    assert harness.timeouts()[-1] == 15


def test_processing_get_limit_is_shared_across_files() -> None:
    first = "files/first"
    second = "files/second"
    harness = _Harness(
        [{"file": _metadata("PROCESSING", first)}, {"file": _metadata("PROCESSING", second)}],
        [_metadata("PROCESSING", first)] * 28
        + [_metadata("ACTIVE", first), _metadata("PROCESSING", second)],
    )
    with pytest.raises(AIProviderError, match="polling limit") as caught:
        harness.provider.complete(_request(2, timeout=300))
    assert not isinstance(caught.value, AIProviderMediaRetentionError)
    assert harness.methods().count("GET") == 30
    assert len(harness.clock.sleeps) == 30
    assert "interaction" not in harness.events
    assert [request.url.path for request in harness.requests[-2:]] == [
        f"/v1beta/{second}",
        f"/v1beta/{first}",
    ]


@pytest.mark.parametrize("delete_fails", [False, True])
def test_get_deadline_expiry_is_retryable_only_after_confirmed_cleanup(delete_fails: bool) -> None:
    harness = _Harness([{"file": _metadata("PROCESSING")}], [_metadata()])
    harness.latencies = {"get": deque([19])}
    if delete_fails:
        harness.deletions.append(httpx.Response(503))
    with pytest.raises(AIProviderError) as caught:
        harness.provider.complete(_request())
    assert isinstance(caught.value, AIProviderMediaRetentionError) is delete_fails
    assert harness.methods() == ["POST", "POST", "GET", "DELETE"]


def test_trickling_get_body_respects_shared_deadline() -> None:
    harness = _Harness([{"file": _metadata("PROCESSING")}])

    class _SlowBody(httpx.SyncByteStream):
        closed = False

        def __iter__(self) -> Iterator[bytes]:
            yield b"{"
            harness.clock.now += 20
            yield b"}"

        def close(self) -> None:
            self.closed = True

    body = _SlowBody()
    harness.gets.append(httpx.Response(200, stream=body))
    with pytest.raises(AIProviderError, match="work time limit"):
        harness.provider.complete(_request())
    assert body.closed
    assert harness.methods() == ["POST", "POST", "GET", "DELETE"]


@pytest.mark.parametrize("renew_index", [3, 4, 5, 6])
def test_lease_failure_around_wait_and_get_preserves_original_retention_error(
    renew_index: int,
) -> None:
    harness = _Harness([{"file": _metadata("PROCESSING")}], [_metadata()])
    original = AIProviderMediaRetentionError("Synthetic durable lease failure")

    def fail_renewal() -> None:
        raise original

    harness.journal.renew_effects[renew_index] = fail_renewal
    harness.deletions.append(httpx.Response(503))
    with pytest.raises(AIProviderMediaRetentionError) as caught:
        harness.provider.complete(_request())
    assert caught.value is original
    assert "interaction" not in harness.events
    assert harness.methods()[-1] == "DELETE"


def test_cleanup_network_budget_traverses_every_durable_obligation_after_expiry() -> None:
    harness = _Harness([{"file": _metadata(name=f"files/image-{index}")} for index in range(4)])
    harness.latencies = {"delete": deque([15, 14, 1])}
    with pytest.raises(AIProviderMediaRetentionError):
        harness.provider.complete(_request(4))
    assert harness.timeouts()[-3:] == [15, 15, 1]
    assert harness.methods().count("DELETE") == 3
    assert [event for event in harness.events if event.startswith("obligation:")] == [
        "obligation:files/image-3",
        "obligation:files/image-2",
        "obligation:files/image-1",
        "obligation:files/image-0",
    ]
    records = harness.journal.durable._repository.list_public()
    assert len(records) == 1 and records[0].state is MediaCleanupState.DELETE_PENDING
    assert records[0].reason == "DELETE_FAILED" and records[0].lease_until is None


def test_cleanup_rechecks_remaining_time_after_client_construction() -> None:
    harness = _Harness([{"file": _metadata(name=f"files/image-{index}")} for index in range(2)])

    def slow_client_factory(
        *, timeout: float, transport: httpx.BaseTransport | None, follow_redirects: bool
    ) -> httpx.Client:
        if "cleanup" in harness.events:
            harness.clock.now += 30
        return httpx.Client(timeout=timeout, transport=transport, follow_redirects=follow_redirects)

    harness.provider._client_factory = slow_client_factory
    with pytest.raises(AIProviderMediaRetentionError):
        harness.provider.complete(_request(2))
    assert harness.methods().count("DELETE") == 0
    assert sum(event.startswith("obligation:") for event in harness.events) == 2
    records = harness.journal.durable._repository.list_public()
    assert len(records) == 2
    assert all(record.state is MediaCleanupState.DELETE_PENDING for record in records)


def test_expiry_during_post_interaction_renewal_does_not_return_success() -> None:
    harness = _Harness()
    harness.journal.renew_effects[4] = lambda: setattr(harness.clock, "now", 120.0)
    with pytest.raises(AIProviderError, match="work time limit") as caught:
        harness.provider.complete(_request())
    assert not isinstance(caught.value, AIProviderMediaRetentionError)
    assert harness.methods() == ["POST", "POST", "POST", "DELETE"]


def test_active_response_on_last_permitted_poll_is_usable() -> None:
    harness = _Harness(
        [{"file": _metadata("PROCESSING")}], [_metadata("PROCESSING")] * 29 + [_metadata()]
    )
    assert harness.provider.complete(_request(timeout=100)).content == "Reviewed"
    assert harness.methods().count("GET") == 30
    assert harness.methods()[-2:] == ["POST", "DELETE"]


@pytest.mark.parametrize(("media_count", "delete_fails"), [(0, False), (1, False), (1, True)])
def test_response_construction_deadline_expiry_preserves_cleanup_precedence(
    media_count: int, delete_fails: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _Harness()
    if delete_fails:
        harness.deletions.append(httpx.Response(503))

    def slow_response(**values: object) -> AIProviderResponse:
        result = AIProviderResponse.model_validate(values)
        harness.clock.now += 2
        return result

    monkeypatch.setattr("job_apply_pro.ai.providers.AIProviderResponse", slow_response)
    with pytest.raises(AIProviderError) as caught:
        harness.provider.complete(_request(media_count, timeout=1))
    assert isinstance(caught.value, AIProviderMediaRetentionError) is delete_fails
    if not delete_fails:
        assert "work time limit" in str(caught.value)
    if media_count:
        assert harness.methods() == ["POST", "POST", "POST", "DELETE"]
        assert harness.timeouts()[-1] == 15
    else:
        assert harness.methods() == ["POST"]
        assert "cleanup" not in harness.events
