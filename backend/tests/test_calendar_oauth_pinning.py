"""Calendar credentials stay pinned to the reviewed connection across token races."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.domain.communications import IntegrationProvider, OAuthTokenSet
from job_apply_pro.integrations.communications import (
    ProviderCalendarNotAppliedError,
    ProviderMutationError,
)
from job_apply_pro.integrations.configuration import OAuthClientConfig
from job_apply_pro.integrations.oauth import (
    BoundCalendarTokenProvider,
    OAuthAuthorizationError,
    OAuthConnectionService,
)
from job_apply_pro.integrations.provider_clients import (
    GoogleCalendarProvider,
    OutlookCalendarProvider,
    _calendar_native_attempt_key,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.storage.models import OAuthCredentialRow
from job_apply_pro.storage.oauth_repository import OAuthRepository
from test_calendar_provider_admission import event, streamed_response

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
REFERENCE_A = "oauth:synthetic:connection-a"
REFERENCE_B = "oauth:synthetic:connection-b"
PROVIDERS = [IntegrationProvider.GOOGLE_CALENDAR, IntegrationProvider.OUTLOOK_CALENDAR]


def cipher() -> SensitiveDataCipher:
    return SensitiveDataCipher(StaticKeyProvider(b"c" * 32))


def tokens(name: str, *, expired: bool = False) -> OAuthTokenSet:
    return OAuthTokenSet(
        access_token=SecretStr(f"synthetic-access-{name}"),
        refresh_token=SecretStr(f"synthetic-refresh-{name}"),
        expires_at=NOW + timedelta(minutes=-1 if expired else 60),
        granted_scopes=["openid", "email"],
        account_hint=f"{name}@example.invalid",
        account_identity=f"synthetic-stable-account-{name}",
    )


def service(
    repository: OAuthRepository,
    provider: IntegrationProvider,
    handler: Callable[[httpx.Request], httpx.Response],
) -> OAuthConnectionService:
    return OAuthConnectionService(
        repository,
        {
            provider: OAuthClientConfig(
                provider=provider,
                client_id="synthetic-public-client",
                requested_scopes=["openid", "email"],
            )
        },
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
        now=lambda: NOW,
    )


def no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError("This operation must not issue any network request")


def adapter(
    oauth: OAuthConnectionService,
    provider: IntegrationProvider,
    handler: Callable[[httpx.Request], httpx.Response],
) -> GoogleCalendarProvider | OutlookCalendarProvider:
    bound = BoundCalendarTokenProvider(oauth, provider, REFERENCE_A)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return (
        GoogleCalendarProvider(bound, client=client)
        if provider == IntegrationProvider.GOOGLE_CALENDAR
        else OutlookCalendarProvider(bound, client=client)
    )


@pytest.mark.parametrize("provider", PROVIDERS)
def test_bound_calendar_resolves_only_exact_calendar_provider_and_hides_private_reference(
    session: Session, provider: IntegrationProvider
) -> None:
    repository = OAuthRepository(session, cipher())
    repository.save_tokens(provider, REFERENCE_A, tokens("a"), now=NOW)
    oauth = service(repository, provider, no_network)
    bound = BoundCalendarTokenProvider(oauth, provider, REFERENCE_A)
    assert bound.access_token(provider) == "synthetic-access-a"
    assert REFERENCE_A not in repr(bound) and "oauth=" not in repr(bound)
    for other in IntegrationProvider:
        if other != provider:
            with pytest.raises(OAuthAuthorizationError, match="does not match"):
                bound.access_token(other)
    with pytest.raises(OAuthAuthorizationError, match="does not match"):
        BoundCalendarTokenProvider(oauth, IntegrationProvider.GMAIL, REFERENCE_A).access_token(
            IntegrationProvider.GMAIL
        )
    with pytest.raises(OAuthAuthorizationError, match="unavailable"):
        BoundCalendarTokenProvider(oauth, provider, "").access_token(provider)


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("expired", [False, True])
def test_reconnect_before_calendar_resolution_never_refreshes_or_posts(
    session: Session, provider: IntegrationProvider, expired: bool
) -> None:
    repository = OAuthRepository(session, cipher())
    repository.save_tokens(provider, REFERENCE_A, tokens("a", expired=expired), now=NOW)
    oauth = service(repository, provider, no_network)
    provider_adapter = adapter(oauth, provider, no_network)
    repository.save_tokens(provider, REFERENCE_B, tokens("b", expired=expired), now=NOW)
    with pytest.raises(ProviderCalendarNotAppliedError) as raised:
        provider_adapter.create_event(event(), idempotency_key="local-claim")
    assert type(raised.value) is ProviderCalendarNotAppliedError
    assert str(raised.value) == "Calendar provider authorization is unavailable"
    stored = repository.load_tokens(provider)
    assert stored is not None and stored[0] == REFERENCE_B


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("replacement", ["reconnect", "revoke"])
def test_calendar_refresh_race_cannot_overwrite_connection_or_reach_calendar_post(
    session: Session, provider: IntegrationProvider, replacement: str
) -> None:
    repository = OAuthRepository(session, cipher())
    repository.save_tokens(provider, REFERENCE_A, tokens("a", expired=True), now=NOW)
    requests: list[httpx.Request] = []

    def refresh(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.endswith("/token")
        assert b"synthetic-refresh-a" in request.content
        with Session(session.get_bind()) as concurrent:
            other = OAuthRepository(concurrent, cipher())
            if replacement == "reconnect":
                other.save_tokens(provider, REFERENCE_B, tokens("b"), now=NOW)
            else:
                assert other.delete_tokens(provider)
        return httpx.Response(200, json={"access_token": "synthetic-late-a", "expires_in": 3600})

    oauth = service(repository, provider, refresh)
    with pytest.raises(ProviderCalendarNotAppliedError) as raised:
        adapter(oauth, provider, no_network).create_event(event(), idempotency_key="local-claim")
    assert type(raised.value) is ProviderCalendarNotAppliedError
    assert str(raised.value) == "Calendar provider authorization is unavailable"
    assert len(requests) == 1
    session.expire_all()
    stored = repository.load_tokens(provider)
    if replacement == "reconnect":
        assert stored is not None and stored[0] == REFERENCE_B
        assert stored[1].access_token.get_secret_value() == "synthetic-access-b"
    else:
        assert stored is None


@pytest.mark.parametrize("provider", PROVIDERS)
def test_calendar_refresh_preserves_reviewed_reference_stable_identity_and_encryption(
    session: Session, provider: IntegrationProvider
) -> None:
    repository = OAuthRepository(session, cipher())
    repository.save_tokens(provider, REFERENCE_A, tokens("a", expired=True), now=NOW)
    requests: list[httpx.Request] = []

    def refresh(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "synthetic-refreshed-a",
                "refresh_token": "synthetic-rotated-a",
                "expires_in": 3600,
            },
        )

    bound = BoundCalendarTokenProvider(
        service(repository, provider, refresh), provider, REFERENCE_A
    )
    assert bound.access_token(provider) == "synthetic-refreshed-a"
    stored = repository.load_tokens(provider)
    assert stored is not None and stored[0] == REFERENCE_A
    assert stored[1].account_identity == "synthetic-stable-account-a"
    assert stored[1].account_hint == "a@example.invalid"
    assert stored[1].refresh_token is not None
    assert stored[1].refresh_token.get_secret_value() == "synthetic-rotated-a"
    row = session.scalar(select(OAuthCredentialRow))
    assert row is not None
    assert "synthetic-refreshed-a" not in row.encrypted_token_set
    assert "synthetic-rotated-a" not in row.encrypted_token_set
    assert bound.access_token(provider) == "synthetic-refreshed-a"
    assert len(requests) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
def test_calendar_post_uses_resolved_a_token_when_reconnected_after_resolution(
    session: Session, provider: IntegrationProvider
) -> None:
    repository = OAuthRepository(session, cipher())
    repository.save_tokens(provider, REFERENCE_A, tokens("a"), now=NOW)
    requests: list[httpx.Request] = []

    def post(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        repository.save_tokens(provider, REFERENCE_B, tokens("b"), now=NOW)
        assert request.headers["Authorization"] == "Bearer synthetic-access-a"
        return (
            streamed_response(
                200,
                ('{"id":"' + _calendar_native_attempt_key("local-claim", provider) + '"}').encode(),
            )
            if provider == IntegrationProvider.GOOGLE_CALENDAR
            else streamed_response(201, b'{"id":"AAMkSynthetic-1"}')
        )

    provider_adapter = adapter(service(repository, provider, no_network), provider, post)
    provider_adapter.create_event(event(), idempotency_key="local-claim")
    with pytest.raises(ProviderMutationError, match="authorization is unavailable"):
        provider_adapter.create_event(event(), idempotency_key="another-local-claim")
    assert len(requests) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("failure", ["redirect", "transport", "invalid-json"])
def test_calendar_refresh_failure_is_definite_sanitized_without_redirect_or_mutation_post(
    session: Session, provider: IntegrationProvider, failure: str
) -> None:
    repository = OAuthRepository(session, cipher())
    repository.save_tokens(provider, REFERENCE_A, tokens("a", expired=True), now=NOW)
    requests: list[httpx.Request] = []

    def refresh(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "redirect":
            return httpx.Response(307, headers={"Location": "https://attacker.invalid/collect"})
        if failure == "transport":
            raise httpx.ReadTimeout("synthetic private refresh failure")
        return httpx.Response(200, content=b"private invalid json")

    with pytest.raises(ProviderCalendarNotAppliedError) as raised:
        adapter(service(repository, provider, refresh), provider, no_network).create_event(
            event(), idempotency_key="local-claim"
        )
    assert type(raised.value) is ProviderCalendarNotAppliedError
    assert str(raised.value) == "Calendar provider authorization is unavailable"
    assert len(requests) == 1
    stored = repository.load_tokens(provider)
    assert stored is not None and stored[0] == REFERENCE_A
    assert stored[1].access_token.get_secret_value() == "synthetic-access-a"
