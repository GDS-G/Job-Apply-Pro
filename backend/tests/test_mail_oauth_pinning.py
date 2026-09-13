from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.domain.communications import (
    IntegrationProvider,
    MessageCategory,
    OAuthTokenSet,
    OutboundDraft,
    OutboundPolicy,
)
from job_apply_pro.integrations.communications import ProviderMutationError
from job_apply_pro.integrations.configuration import OAuthClientConfig
from job_apply_pro.integrations.oauth import (
    BoundMailTokenProvider,
    OAuthAuthorizationError,
    OAuthConnectionService,
)
from job_apply_pro.integrations.provider_clients import GmailMessageProvider, OutlookMessageProvider
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.storage.models import OAuthCredentialRow
from job_apply_pro.storage.oauth_repository import OAuthRepository

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
REFERENCE_A = "oauth:fixture:connection-a"
REFERENCE_B = "oauth:fixture:connection-b"
MAIL_PROVIDERS = [IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK]


def _cipher() -> SensitiveDataCipher:
    return SensitiveDataCipher(StaticKeyProvider(b"p" * 32))


def _tokens(name: str, *, expired: bool = False) -> OAuthTokenSet:
    return OAuthTokenSet(
        access_token=SecretStr(f"synthetic-access-{name}"),
        refresh_token=SecretStr(f"synthetic-refresh-{name}"),
        expires_at=NOW + timedelta(minutes=-1 if expired else 60),
        granted_scopes=["openid", "email"],
        account_hint=f"{name}@example.invalid",
    )


def _service(
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


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError("This operation must not issue any network request")


@pytest.mark.parametrize("provider", MAIL_PROVIDERS)
@pytest.mark.parametrize("expired", [False, True])
def test_reconnect_before_bound_resolution_rejects_before_token_or_refresh(
    session: Session, provider: IntegrationProvider, expired: bool
) -> None:
    repository = OAuthRepository(session, _cipher())
    repository.save_tokens(provider, REFERENCE_A, _tokens("a", expired=expired), now=NOW)
    oauth = _service(repository, provider, _no_network)
    bound = BoundMailTokenProvider(oauth, provider, REFERENCE_A)
    repository.save_tokens(provider, REFERENCE_B, _tokens("b", expired=expired), now=NOW)

    with pytest.raises(OAuthAuthorizationError, match="connection changed") as error:
        bound.access_token(provider)
    assert str(error.value) == "The reviewed provider connection changed"
    assert "synthetic" not in str(error.value)
    assert REFERENCE_A not in repr(bound)
    stored = repository.load_tokens(provider)
    assert stored is not None and stored[0] == REFERENCE_B


@pytest.mark.parametrize("provider", MAIL_PROVIDERS)
def test_bound_resolution_uses_exact_current_connection_without_refresh(
    session: Session, provider: IntegrationProvider
) -> None:
    repository = OAuthRepository(session, _cipher())
    repository.save_tokens(provider, REFERENCE_A, _tokens("a"), now=NOW)
    oauth = _service(repository, provider, _no_network)
    assert BoundMailTokenProvider(oauth, provider, REFERENCE_A).access_token(provider) == (
        "synthetic-access-a"
    )
    with pytest.raises(OAuthAuthorizationError, match="does not match"):
        BoundMailTokenProvider(oauth, provider, REFERENCE_A).access_token(
            IntegrationProvider.GOOGLE_CALENDAR
        )
    with pytest.raises(OAuthAuthorizationError, match="unavailable"):
        oauth.access_token_bound(provider, "")


@pytest.mark.parametrize("provider", MAIL_PROVIDERS)
@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("replacement", ["reconnect", "revoke"])
def test_refresh_cannot_overwrite_a_concurrent_reconnection_or_revocation(
    session: Session, provider: IntegrationProvider, bound: bool, replacement: str
) -> None:
    repository = OAuthRepository(session, _cipher())
    repository.save_tokens(provider, REFERENCE_A, _tokens("a", expired=True), now=NOW)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.endswith("/token")
        assert b"synthetic-refresh-a" in request.content
        # A second database session commits a new login while A's refresh is in flight.
        with Session(session.get_bind()) as concurrent:
            other = OAuthRepository(concurrent, _cipher())
            if replacement == "reconnect":
                other.save_tokens(provider, REFERENCE_B, _tokens("b"), now=NOW)
            else:
                assert other.delete_tokens(provider)
        return httpx.Response(
            200, json={"access_token": "synthetic-late-refresh-a", "expires_in": 3600}
        )

    oauth = _service(repository, provider, handler)
    with pytest.raises(OAuthAuthorizationError, match="connection changed"):
        if bound:
            oauth.access_token_bound(provider, REFERENCE_A)
        else:
            oauth.access_token(provider)
    assert len(requests) == 1
    session.expire_all()
    stored = repository.load_tokens(provider)
    if replacement == "reconnect":
        assert stored is not None
        assert stored[0] == REFERENCE_B
        assert stored[1].access_token.get_secret_value() == "synthetic-access-b"
    else:
        assert stored is None


@pytest.mark.parametrize("provider", MAIL_PROVIDERS)
def test_successful_bound_refresh_keeps_reference_and_encrypted_rotated_tokens(
    session: Session, provider: IntegrationProvider
) -> None:
    repository = OAuthRepository(session, _cipher())
    repository.save_tokens(provider, REFERENCE_A, _tokens("a", expired=True), now=NOW)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "synthetic-refreshed-a",
                "refresh_token": "synthetic-rotated-refresh-a",
                "expires_in": 3600,
            },
        )

    oauth = _service(repository, provider, handler)
    assert oauth.access_token_bound(provider, REFERENCE_A) == "synthetic-refreshed-a"
    stored = repository.load_tokens(provider)
    assert stored is not None and stored[0] == REFERENCE_A
    assert stored[1].refresh_token is not None
    assert stored[1].refresh_token.get_secret_value() == "synthetic-rotated-refresh-a"
    row = session.scalar(select(OAuthCredentialRow))
    assert row is not None
    assert "synthetic-refreshed-a" not in row.encrypted_token_set
    assert "synthetic-rotated-refresh-a" not in row.encrypted_token_set
    assert oauth.access_token_bound(provider, REFERENCE_A) == "synthetic-refreshed-a"
    assert len(requests) == 1


def test_conditional_repository_refresh_never_creates_or_changes_another_provider(
    session: Session,
) -> None:
    repository = OAuthRepository(session, _cipher())
    assert not repository.refresh_tokens_if_current(
        IntegrationProvider.GMAIL, REFERENCE_A, _tokens("late-a"), now=NOW
    )
    assert repository.load_tokens(IntegrationProvider.GMAIL) is None
    repository.save_tokens(IntegrationProvider.GMAIL, REFERENCE_A, _tokens("a"), now=NOW)
    assert not repository.refresh_tokens_if_current(
        IntegrationProvider.OUTLOOK, REFERENCE_A, _tokens("late-a"), now=NOW
    )
    stored = repository.load_tokens(IntegrationProvider.GMAIL)
    assert stored is not None and stored[1].access_token.get_secret_value() == "synthetic-access-a"
    assert repository.load_tokens(IntegrationProvider.OUTLOOK) is None


@pytest.mark.parametrize("provider", MAIL_PROVIDERS)
def test_provider_post_keeps_the_resolved_a_token_when_b_connects_after_resolution(
    session: Session, provider: IntegrationProvider
) -> None:
    repository = OAuthRepository(session, _cipher())
    repository.save_tokens(provider, REFERENCE_A, _tokens("a"), now=NOW)
    oauth = _service(repository, provider, _no_network)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        repository.save_tokens(provider, REFERENCE_B, _tokens("b"), now=NOW)
        assert request.headers["Authorization"] == "Bearer synthetic-access-a"
        return (
            httpx.Response(200, json={"id": "synthetic-message-id"})
            if provider is (IntegrationProvider.GMAIL)
            else httpx.Response(202)
        )

    draft = OutboundDraft(
        id="draft-1",
        analysis_id="analysis-1",
        provider=provider,
        provider_thread_id="thread-1",
        recipient="recruiter@example.invalid",
        subject="Reviewed fixture",
        body_text="Synthetic body",
        category=MessageCategory.RECRUITER_INQUIRY,
        policy=OutboundPolicy.REVIEW_REQUIRED,
        document_version_ids=[],
        fingerprint="a" * 64,
        created_at=NOW,
        updated_at=NOW,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        tokens = BoundMailTokenProvider(oauth, provider, REFERENCE_A)
        adapter = (
            GmailMessageProvider(tokens, client=client)
            if provider is (IntegrationProvider.GMAIL)
            else OutlookMessageProvider(tokens, client=client)
        )
        adapter.send(draft, idempotency_key="synthetic-send-key")
        with pytest.raises(ProviderMutationError, match="connection changed"):
            adapter.send(draft, idempotency_key="synthetic-second-key")
    assert len(requests) == 1


@pytest.mark.parametrize("failure", ["redirect", "transport", "invalid-json"])
def test_refresh_failure_is_static_and_does_not_mutate_credentials(
    session: Session, failure: str
) -> None:
    repository = OAuthRepository(session, _cipher())
    repository.save_tokens(
        IntegrationProvider.GMAIL, REFERENCE_A, _tokens("a", expired=True), now=NOW
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "redirect":
            return httpx.Response(307, headers={"Location": "https://untrusted.invalid/collect"})
        if failure == "transport":
            raise httpx.ReadTimeout("synthetic-private-transport-context")
        return httpx.Response(200, content=b"synthetic-private-invalid-json")

    oauth = _service(repository, IntegrationProvider.GMAIL, handler)
    with pytest.raises(OAuthAuthorizationError) as error:
        oauth.access_token_bound(IntegrationProvider.GMAIL, REFERENCE_A)
    assert str(error.value) == "Provider token refresh failed"
    assert len(requests) == 1
    stored = repository.load_tokens(IntegrationProvider.GMAIL)
    assert stored is not None and stored[0] == REFERENCE_A
    assert stored[1].access_token.get_secret_value() == "synthetic-access-a"
