"""Synthetic one-attempt calendar transport and pre-dispatch validation boundaries."""

import json
import time
from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest

from job_apply_pro.domain.communications import (
    CalendarCreateFields,
    CalendarEventSnapshot,
    IntegrationProvider,
)
from job_apply_pro.integrations.communications import (
    FixtureCalendarProvider,
    ProviderCalendarNotAppliedError,
    ProviderCalendarUncertainError,
    ProviderMutationError,
    validate_calendar_create,
)
from job_apply_pro.integrations.oauth import OAuthAuthorizationError
from job_apply_pro.integrations.provider_clients import (
    GoogleCalendarProvider,
    OutlookCalendarProvider,
    _calendar_native_attempt_key,
)

PROVIDERS = [GoogleCalendarProvider, OutlookCalendarProvider]
ProviderClass = type[GoogleCalendarProvider] | type[OutlookCalendarProvider]


def event() -> CalendarCreateFields:
    start = datetime(2026, 9, 20, 15, tzinfo=UTC)
    return CalendarCreateFields(
        title="Reviewed interview",
        start_at=start,
        end_at=start + timedelta(hours=1),
        time_zone="UTC",
        attendees=[],
        attendee_notification_policy="NONE",
        location="Reviewed location",
    )


class Tokens:
    def __init__(self, *, value: str = "synthetic-token", error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.calls: list[IntegrationProvider] = []

    def access_token(self, provider: IntegrationProvider) -> str:
        self.calls.append(provider)
        if self.error is not None:
            raise self.error
        return self.value


def success(provider: ProviderClass, idempotency_key: str = "local-audit-key") -> tuple[int, str]:
    if provider is GoogleCalendarProvider:
        return 200, _calendar_native_attempt_key(
            idempotency_key, IntegrationProvider.GOOGLE_CALENDAR
        )
    return 201, "AAMkSynthetic_ID-1+/=="


def streamed_response(status: int, body: bytes) -> httpx.Response:
    return httpx.Response(status, stream=httpx.ByteStream(body))


class Stream(httpx.SyncByteStream):
    def __init__(
        self, chunks: list[bytes], *, fail_read: bool = False, fail_close: bool = False
    ) -> None:
        self.chunks = chunks
        self.fail_read = fail_read
        self.fail_close = fail_close
        self.reads = 0
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.chunks:
            self.reads += 1
            yield chunk
        if self.fail_read:
            raise httpx.ReadError("synthetic private read failure")

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise RuntimeError("synthetic private cleanup failure")


@pytest.mark.parametrize("provider", PROVIDERS)
def test_create_is_one_fixed_primary_post_with_native_dedupe_and_no_fake_header(
    provider: ProviderClass,
) -> None:
    requests: list[httpx.Request] = []
    status, identifier = success(provider)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return streamed_response(status, json.dumps({"id": identifier}).encode())

    tokens = Tokens()
    adapter = provider(tokens, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert adapter.create_event(event(), idempotency_key="local-audit-key") == identifier
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == (
        "https://www.googleapis.com/calendar/v3/calendars/primary/events?sendUpdates=none"
        if provider is GoogleCalendarProvider
        else "https://graph.microsoft.com/v1.0/me/events"
    )
    assert request.headers["Authorization"] == "Bearer synthetic-token"
    assert request.headers["Accept-Encoding"] == "identity"
    assert "X-Job-Apply-Pro-Idempotency-Key" not in request.headers
    payload = json.loads(request.content)
    assert "provider_event_id" not in payload
    native_key = _calendar_native_attempt_key("local-audit-key", adapter.provider)
    if provider is GoogleCalendarProvider:
        assert payload["id"] == native_key
        assert "transactionId" not in payload
    else:
        assert payload["transactionId"] == native_key
        assert "id" not in payload
        assert payload["allowNewTimeProposals"] is False
    assert payload.get("attendees", []) == []
    expected_start = (
        event().start_at.isoformat()
        if provider is GoogleCalendarProvider
        else event().start_at.replace(tzinfo=None).isoformat()
    )
    expected_end = (
        event().end_at.isoformat()
        if provider is GoogleCalendarProvider
        else event().end_at.replace(tzinfo=None).isoformat()
    )
    assert payload["start"] == {"dateTime": expected_start, "timeZone": "UTC"}
    assert payload["end"] == {"dateTime": expected_end, "timeZone": "UTC"}
    if provider is GoogleCalendarProvider:
        assert payload["reminders"] == {"useDefault": False, "overrides": []}
        assert payload["visibility"] == "private"
        assert payload["transparency"] == "opaque"
    else:
        assert payload["isReminderOn"] is False
        assert payload["sensitivity"] == "private"
        assert payload["showAs"] == "busy"
        assert payload["responseRequested"] is False
    assert len(request.content) <= 65_536
    assert tokens.calls == [adapter.provider]
    assert request.extensions["timeout"] == {
        "connect": 30.0,
        "read": 30.0,
        "write": 30.0,
        "pool": 30.0,
    }


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 415, 422, 429])
def test_known_rejection_is_definite_only_after_clean_response_close(
    provider: ProviderClass, status: int
) -> None:
    requests: list[httpx.Request] = []
    stream = Stream([b"private provider details"])

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, stream=stream)

    adapter = provider(Tokens(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderCalendarNotAppliedError) as raised:
        adapter.create_event(event(), idempotency_key="local-audit-key")
    assert type(raised.value) is ProviderCalendarNotAppliedError
    assert str(raised.value) == "The calendar provider rejected the create request"
    assert len(requests) == 1
    assert stream.closed
    assert stream.reads == 0


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("status", [202, 204, 206, 301, 302, 307, 308, 408, 409, 500, 502, 503])
def test_redirect_unexpected_success_or_unknown_status_is_uncertain_without_follow_or_retry(
    provider: ProviderClass, status: int
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://attacker.invalid/collect"},
            json={"id": success(provider)[1]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with pytest.raises(ProviderCalendarUncertainError) as raised:
        provider(Tokens(), client=client).create_event(event(), idempotency_key="local-audit-key")
    assert "attacker" not in str(raised.value)
    assert len(requests) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not-json",
        b"[]",
        b"{}",
        b'{"id": 4}',
        b'{"id": ""}',
        b'{"id": "unsafe\\r\\nvalue"}',
        b'{"id": "white space"}',
        b'{"id": "../other"}',
        b'{"id":"\xff"}',
    ],
)
def test_invalid_expected_status_response_is_uncertain(
    provider: ProviderClass, body: bytes
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return streamed_response(success(provider)[0], body)

    with pytest.raises(ProviderCalendarUncertainError):
        provider(
            Tokens(), client=httpx.Client(transport=httpx.MockTransport(handler))
        ).create_event(event(), idempotency_key="local-audit-key")
    assert len(requests) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
def test_opposite_provider_success_status_and_oversized_identifier_are_uncertain(
    provider: ProviderClass,
) -> None:
    for status, identifier in [
        (201 if provider is GoogleCalendarProvider else 200, success(provider)[1]),
        (success(provider)[0], "a" * 501),
    ]:
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request, status=status, identifier=identifier: streamed_response(
                    status, json.dumps({"id": identifier}).encode()
                )
            )
        )
        with pytest.raises(ProviderCalendarUncertainError):
            provider(Tokens(), client=client).create_event(
                event(), idempotency_key="local-audit-key"
            )


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "failure", ["oversized", "read", "cleanup-success", "cleanup-rejection", "transport"]
)
def test_postdispatch_transport_stream_size_and_cleanup_failures_are_uncertain(
    provider: ProviderClass, failure: str
) -> None:
    requests: list[httpx.Request] = []
    body = json.dumps({"id": success(provider)[1]}).encode()
    stream = Stream(
        [b"x" * 65_537] if failure == "oversized" else [body],
        fail_read=failure == "read",
        fail_close=failure.startswith("cleanup"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "transport":
            raise httpx.ConnectError("synthetic secret transport failure")
        return httpx.Response(
            400 if failure == "cleanup-rejection" else success(provider)[0], stream=stream
        )

    with pytest.raises(ProviderCalendarUncertainError) as raised:
        provider(
            Tokens(), client=httpx.Client(transport=httpx.MockTransport(handler))
        ).create_event(event(), idempotency_key="local-audit-key")
    assert len(requests) == 1
    assert "synthetic" not in str(raised.value)
    if failure != "transport":
        assert stream.closed


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "identity, gzip", ""])
def test_unexpected_response_encoding_is_uncertain_before_body_is_read(
    provider: ProviderClass, encoding: str
) -> None:
    calls: list[httpx.Request] = []
    stream = Stream([json.dumps({"id": success(provider)[1]}).encode()])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(
            success(provider)[0], headers={"Content-Encoding": encoding}, stream=stream
        )

    with pytest.raises(ProviderCalendarUncertainError):
        provider(
            Tokens(), client=httpx.Client(transport=httpx.MockTransport(handler))
        ).create_event(event(), idempotency_key="local-audit-key")
    assert len(calls) == 1
    assert stream.reads == 0 and stream.closed


@pytest.mark.parametrize("provider", PROVIDERS)
def test_explicit_identity_encoding_retains_bounded_raw_body(provider: ProviderClass) -> None:
    body = json.dumps({"id": success(provider)[1]}).encode()
    stream = Stream([b" " * (65_536 - len(body)), body])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            success(provider)[0], headers={"Content-Encoding": "identity"}, stream=stream
        )

    adapter = provider(Tokens(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert adapter.create_event(event(), idempotency_key="local-audit-key") == success(provider)[1]
    assert stream.reads == 2 and stream.closed


@pytest.mark.parametrize("provider", PROVIDERS)
def test_injected_auth_challenge_handler_cannot_replay_calendar_post(
    provider: ProviderClass,
) -> None:
    calls: list[httpx.Request] = []

    class ReplayAuth(httpx.Auth):
        def auth_flow(
            self, request: httpx.Request
        ) -> Generator[httpx.Request, httpx.Response, None]:
            raise AssertionError("Provider request must not use injected challenge auth")
            yield request

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401)

    client = httpx.Client(transport=httpx.MockTransport(handler), auth=ReplayAuth())
    with pytest.raises(ProviderCalendarNotAppliedError) as raised:
        provider(Tokens(), client=client).create_event(event(), idempotency_key="local-audit-key")
    assert type(raised.value) is ProviderCalendarNotAppliedError
    assert len(calls) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
def test_stream_deadline_is_checked_for_each_unaggregated_chunk(
    provider: ProviderClass, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 0.0
    chunks = 0

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            nonlocal now, chunks
            for _ in range(1_000):
                now += 6.0
                chunks += 1
                yield b" "

    monkeypatch.setattr(time, "monotonic", lambda: now)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(success(provider)[0], stream=SlowStream())
        )
    )
    with pytest.raises(ProviderCalendarUncertainError):
        provider(Tokens(), client=client).create_event(event(), idempotency_key="local-audit-key")
    assert chunks == 5


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "token", ["", "contains space", "private\r\ninjected", "\u00e9", "x" * 16_385]
)
def test_invalid_authorization_is_definite_before_transport(
    provider: ProviderClass, token: str
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: pytest.fail("Invalid token must not reach HTTP")
        )
    )
    with pytest.raises(ProviderCalendarNotAppliedError) as raised:
        provider(Tokens(value=token), client=client).create_event(
            event(), idempotency_key="local-audit-key"
        )
    assert type(raised.value) is ProviderCalendarNotAppliedError
    assert str(raised.value) == "Calendar provider authorization is unavailable"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_authorization_exception_is_sanitized_before_transport(provider: ProviderClass) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: pytest.fail("No HTTP expected"))
    )
    with pytest.raises(ProviderCalendarNotAppliedError) as raised:
        provider(
            Tokens(error=OAuthAuthorizationError("private connection")), client=client
        ).create_event(event(), idempotency_key="local-audit-key")
    assert type(raised.value) is ProviderCalendarNotAppliedError
    assert str(raised.value) == "Calendar provider authorization is unavailable"


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "change",
    [
        {"conferencing_url": "https://private.invalid/meeting"},
        {"attendee_notification_policy": "ALL"},
        {"reminder_policy": "DEFAULT"},
        {"visibility_policy": "PUBLIC"},
        {"availability_policy": "FREE"},
        {"attendees": ["Name <person@example.invalid>"]},
        {"attendees": ["one@example.invalid,two@example.invalid"]},
        {"attendees": ["person@example.invalid"]},
        {"attendees": ["PERSON@example.invalid", "person@example.invalid"]},
        {"attendees": ["person@example.invalid"] * 101},
        {"title": "private\ncontrol"},
        {"title": ""},
        {"title": "   "},
        {"location": "   "},
        {"location": "private\u202econtrol"},
        {"time_zone": "Unknown/Timezone"},
        {"start_at": datetime(2026, 9, 20, 15)},
        {"provider_event_id": "caller-selected-id"},
    ],
)
def test_invalid_or_unreviewable_payload_is_definite_before_token_or_transport(
    provider: ProviderClass, change: dict[str, object]
) -> None:
    reviewed = event().model_copy(update=change)
    tokens = Tokens()
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: pytest.fail("No HTTP expected"))
    )
    with pytest.raises(ValueError, match="Calendar creation payload is invalid or unsupported"):
        validate_calendar_create(reviewed)
    with pytest.raises(ProviderCalendarNotAppliedError) as raised:
        provider(tokens, client=client).create_event(reviewed, idempotency_key="local-audit-key")
    assert type(raised.value) is ProviderCalendarNotAppliedError
    assert tokens.calls == []


@pytest.mark.parametrize("provider", PROVIDERS)
def test_update_fails_closed_before_token_or_transport(provider: ProviderClass) -> None:
    tokens = Tokens()
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: pytest.fail("No HTTP expected"))
    )
    snapshot = CalendarEventSnapshot(
        provider_event_id="legacy-source-id",
        **event().model_dump(
            exclude={
                "attendee_notification_policy",
                "reminder_policy",
                "visibility_policy",
                "availability_policy",
            }
        ),
    )
    with pytest.raises(ProviderMutationError, match="updates are not supported"):
        provider(tokens, client=client).update_event(snapshot, idempotency_key="local-audit-key")
    assert tokens.calls == []


def test_validator_returns_independent_no_repair_copy_and_fixture_assigns_only_its_own_id() -> None:
    original = event()
    validated = validate_calendar_create(original)
    assert validated == original
    assert validated is not original
    assert validated.attendees is not original.attendees
    fixture = FixtureCalendarProvider(IntegrationProvider.GOOGLE_CALENDAR)
    identifier = fixture.create_event(validated, idempotency_key="local-audit-key")
    assert fixture.events[0].provider_event_id == identifier
    assert fixture.events[0].model_dump(exclude={"provider_event_id"}) == original.model_dump(
        exclude={
            "attendee_notification_policy",
            "reminder_policy",
            "visibility_policy",
            "availability_policy",
        }
    )
    with pytest.raises(ProviderMutationError):
        fixture.update_event(fixture.events[0], idempotency_key="new-local-key")
    assert fixture.mutations == [("create", "local-audit-key")]
    with pytest.raises(ValueError):
        validate_calendar_create(cast(CalendarCreateFields, fixture.events[0]))
