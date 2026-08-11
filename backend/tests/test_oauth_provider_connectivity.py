from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.communications import get_oauth_service
from job_apply_pro.config import get_settings
from job_apply_pro.domain.communications import (
    CalendarEventSnapshot,
    DraftCreate,
    IntegrationProvider,
    IntegrationStatus,
    MessageCategory,
    OAuthTokenSet,
    OutboundDraft,
)
from job_apply_pro.integrations.configuration import OAuthClientConfig
from job_apply_pro.integrations.oauth import (
    OAuthAuthorizationError,
    OAuthConfigurationError,
    OAuthConnectionService,
)
from job_apply_pro.integrations.provider_clients import (
    GmailMessageProvider,
    GoogleCalendarProvider,
    OutlookCalendarProvider,
    OutlookMessageProvider,
)
from job_apply_pro.main import create_app
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.storage.models import OAuthAuthorizationSessionRow, OAuthCredentialRow
from job_apply_pro.storage.oauth_repository import OAuthRepository


class StaticTokens:
    def access_token(self, provider: IntegrationProvider) -> str:
        return f"token-for-{provider.value.casefold()}"


def _cipher() -> SensitiveDataCipher:
    return SensitiveDataCipher(StaticKeyProvider(b"o" * 32))


def _oauth_client(provider: IntegrationProvider) -> OAuthClientConfig:
    scopes = {
        IntegrationProvider.GMAIL: [
            "openid",
            "email",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        IntegrationProvider.OUTLOOK: [
            "openid",
            "email",
            "offline_access",
            "User.Read",
            "Mail.Read",
            "Mail.Send",
        ],
        IntegrationProvider.GOOGLE_CALENDAR: [
            "openid",
            "email",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ],
        IntegrationProvider.OUTLOOK_CALENDAR: [
            "openid",
            "email",
            "offline_access",
            "User.Read",
            "Calendars.ReadWrite",
        ],
    }
    return OAuthClientConfig(
        provider=provider,
        client_id=f"public-client-{provider.value.casefold()}",
        requested_scopes=scopes[provider],
    )


def test_oauth_pkce_exchange_is_one_time_encrypted_and_revocable(session: Session) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access-value",
                    "refresh_token": "refresh-value",
                    "expires_in": 3600,
                    "scope": " ".join(_oauth_client(IntegrationProvider.GMAIL).requested_scopes),
                },
            )
        if request.url.path.endswith("/userinfo"):
            return httpx.Response(200, json={"email": "owner@example.test"})
        if request.url.path.endswith("/revoke"):
            return httpx.Response(200)
        return httpx.Response(404)

    repository = OAuthRepository(session, _cipher())
    service = OAuthConnectionService(
        repository,
        {IntegrationProvider.GMAIL: _oauth_client(IntegrationProvider.GMAIL)},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: datetime(2026, 8, 11, 18, tzinfo=UTC),
    )
    authorization = service.start(IntegrationProvider.GMAIL)
    query = parse_qs(urlparse(authorization.authorization_url).query)
    assert query["state"] == [authorization.state]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) >= 43
    pending = session.scalar(select(OAuthAuthorizationSessionRow))
    assert pending is not None
    assert authorization.state not in pending.state_hash
    assert "code_verifier" not in pending.encrypted_code_verifier

    completed = service.complete(code="one-time-code", state=authorization.state)
    assert completed.status is IntegrationStatus.CONNECTED
    assert completed.account_hint == "owner@example.test"
    credential = session.scalar(select(OAuthCredentialRow))
    assert credential is not None
    assert "access-value" not in credential.encrypted_token_set
    assert "refresh-value" not in credential.encrypted_token_set
    assert service.access_token(IntegrationProvider.GMAIL) == "access-value"
    with pytest.raises(OAuthAuthorizationError, match="consumed"):
        service.complete(code="replayed-code", state=authorization.state)

    revoked = service.revoke(IntegrationProvider.GMAIL)
    assert revoked.status is IntegrationStatus.AUTHORIZATION_REQUIRED
    assert repository.load_tokens(IntegrationProvider.GMAIL) is None
    assert [request.url.path for request in requests] == [
        "/token",
        "/v1/userinfo",
        "/revoke",
    ]


def test_oauth_refresh_preserves_rotating_reference_and_rejects_unknown_scopes(
    session: Session,
) -> None:
    current = datetime(2026, 8, 11, 18, tzinfo=UTC)
    repository = OAuthRepository(session, _cipher())
    repository.save_tokens(
        IntegrationProvider.OUTLOOK,
        "oauth:outlook:stable",
        OAuthTokenSet(
            access_token=SecretStr("expired"),
            refresh_token=SecretStr("refresh-value"),
            expires_at=current - timedelta(minutes=1),
            granted_scopes=_oauth_client(IntegrationProvider.OUTLOOK).requested_scopes,
        ),
        now=current,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/token")
        return httpx.Response(
            200,
            json={"access_token": "refreshed", "expires_in": 1800, "scope": "Mail.Read"},
        )

    service = OAuthConnectionService(
        repository,
        {IntegrationProvider.OUTLOOK: _oauth_client(IntegrationProvider.OUTLOOK)},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: current,
    )
    assert service.access_token(IntegrationProvider.OUTLOOK) == "refreshed"
    stored = repository.load_tokens(IntegrationProvider.OUTLOOK)
    assert stored is not None
    assert stored[0] == "oauth:outlook:stable"
    assert stored[1].refresh_token is not None
    assert stored[1].refresh_token.get_secret_value() == "refresh-value"

    invalid = _oauth_client(IntegrationProvider.GMAIL).model_copy(
        update={"requested_scopes": ["https://example.test/unapproved"]}
    )
    with pytest.raises(OAuthConfigurationError, match="Unapproved"):
        OAuthConnectionService(repository, {IntegrationProvider.GMAIL: invalid}).start(
            IntegrationProvider.GMAIL
        )


def test_loopback_callback_uses_one_time_state_without_exposing_local_api_token(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "callback-access",
                    "refresh_token": "callback-refresh",
                    "expires_in": 3600,
                },
            )
        if request.url.path.endswith("/userinfo"):
            return httpx.Response(200, json={"email": "callback@example.test"})
        return httpx.Response(404)

    service = OAuthConnectionService(
        OAuthRepository(session, _cipher()),
        {IntegrationProvider.GMAIL: _oauth_client(IntegrationProvider.GMAIL)},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setenv("JAP_API_TOKEN", "oauth-api-token")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_oauth_service] = lambda: service
    client = TestClient(app)
    try:
        assert client.post("/api/v1/communications/oauth/GMAIL/start").status_code == 401
        started = client.post(
            "/api/v1/communications/oauth/GMAIL/start",
            headers={"X-Job-Apply-Pro-Token": "oauth-api-token"},
        )
        assert started.status_code == 201
        callback = client.get(
            "/api/v1/communications/oauth/callback",
            params={"code": "browser-code", "state": started.json()["state"]},
        )
        assert callback.status_code == 200
        assert callback.json() == {
            "provider": "GMAIL",
            "status": "CONNECTED",
            "account_hint": "callback@example.test",
            "granted_scopes": sorted(_oauth_client(IntegrationProvider.GMAIL).requested_scopes),
        }
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def _draft(provider: IntegrationProvider) -> OutboundDraft:
    command = DraftCreate(
        analysis_id="analysis-1",
        provider=provider,
        provider_thread_id="thread-1",
        recipient="recruiter@example.test",
        subject="Re: Interview",
        body_text="Thank you. I am available Thursday.",
        category=MessageCategory.INTERVIEW_REQUEST,
    )
    return OutboundDraft(
        id="draft-1",
        **command.model_dump(),
        fingerprint="f" * 64,
        created_at=datetime(2026, 8, 11, 18, tzinfo=UTC),
        updated_at=datetime(2026, 8, 11, 18, tzinfo=UTC),
    )


def test_official_mail_adapters_normalize_and_send_with_provider_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/gmail/v1/users/me/messages") and request.method == "GET":
            return httpx.Response(200, json={"messages": [{"id": "gmail-1"}]})
        if path.endswith("/gmail/v1/users/me/messages/gmail-1"):
            return httpx.Response(
                200,
                json={
                    "id": "gmail-1",
                    "threadId": "gmail-thread-1",
                    "internalDate": "1786471200000",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "recruiter@example.test"},
                            {"name": "To", "value": "owner@example.test"},
                            {"name": "Subject", "value": "Interview"},
                        ],
                        "body": {"data": "Q2hvb3NlIGEgdGltZQ"},
                    },
                },
            )
        if path.endswith("/gmail/v1/users/me/messages/send"):
            return httpx.Response(200, json={"id": "gmail-sent-1"})
        if path.endswith("/v1.0/me/messages") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "outlook-1",
                            "conversationId": "outlook-thread-1",
                            "sender": {"emailAddress": {"address": "recruiter@example.test"}},
                            "toRecipients": [{"emailAddress": {"address": "owner@example.test"}}],
                            "subject": "Interview",
                            "bodyPreview": "Choose a time",
                            "receivedDateTime": "2026-08-11T18:00:00Z",
                        }
                    ]
                },
            )
        if path.endswith("/v1.0/me/messages") and request.method == "POST":
            return httpx.Response(201, json={"id": "outlook-draft-1"})
        if path.endswith("/v1.0/me/messages/outlook-draft-1/send"):
            return httpx.Response(202)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gmail = GmailMessageProvider(StaticTokens(), client=client)
    outlook = OutlookMessageProvider(StaticTokens(), client=client)
    assert gmail.list_messages()[0].body_text == "Choose a time"
    assert outlook.list_messages()[0].provider_thread_id == "outlook-thread-1"
    assert gmail.send(_draft(IntegrationProvider.GMAIL), idempotency_key="gmail-send-1") == (
        "gmail-sent-1"
    )
    assert (
        outlook.send(_draft(IntegrationProvider.OUTLOOK), idempotency_key="outlook-send-1")
        == "outlook-draft-1"
    )


def test_official_calendar_adapters_list_create_and_update() -> None:
    start = datetime(2026, 8, 20, 15, tzinfo=UTC)
    event = CalendarEventSnapshot(
        provider_event_id="event-1",
        title="Interview",
        start_at=start,
        end_at=start + timedelta(hours=1),
        time_zone="UTC",
        attendees=["owner@example.test", "recruiter@example.test"],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/calendar/v3/calendars/primary/events") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "google-event-1",
                            "summary": "Interview",
                            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
                            "end": {
                                "dateTime": (start + timedelta(hours=1)).isoformat(),
                                "timeZone": "UTC",
                            },
                            "attendees": [{"email": "owner@example.test"}],
                        }
                    ]
                },
            )
        if "/calendar/v3/calendars/primary/events" in path:
            return httpx.Response(200, json={"id": "google-event-saved"})
        if path.endswith("/v1.0/me/calendarView"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "outlook-event-1",
                            "subject": "Interview",
                            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
                            "end": {
                                "dateTime": (start + timedelta(hours=1)).isoformat(),
                                "timeZone": "UTC",
                            },
                            "attendees": [],
                        }
                    ]
                },
            )
        if "/v1.0/me/events" in path:
            return httpx.Response(200, json={"id": "outlook-event-saved"})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    google = GoogleCalendarProvider(StaticTokens(), client=client)
    outlook = OutlookCalendarProvider(StaticTokens(), client=client)
    assert google.list_events(start_at=start, end_at=start + timedelta(days=1))[0].title == (
        "Interview"
    )
    assert outlook.list_events(start_at=start, end_at=start + timedelta(days=1))[0].title == (
        "Interview"
    )
    assert google.create_event(event, idempotency_key="google-create-1") == ("google-event-saved")
    assert google.update_event(event, idempotency_key="google-update-1") == ("google-event-saved")
    assert outlook.create_event(event, idempotency_key="outlook-create-1") == (
        "outlook-event-saved"
    )
    assert outlook.update_event(event, idempotency_key="outlook-update-1") == (
        "outlook-event-saved"
    )
