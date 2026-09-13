from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.communications import get_communication_service
from job_apply_pro.domain.communications import (
    DraftCreate,
    IntegrationProvider,
    MailMode,
    MailReplyHeaders,
    MessageCategory,
    MutationConfirmation,
    MutationStatus,
    NormalizedMessage,
    OAuthTokenSet,
    OutboundPolicy,
)
from job_apply_pro.integrations.communications import (
    FixtureMessageProvider,
    ProviderSendUncertainError,
)
from job_apply_pro.integrations.configuration import ProviderConnectionConfig
from job_apply_pro.integrations.oauth import OAuthConnectionService
from job_apply_pro.main import app
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.communications import CommunicationService
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.models import (
    CommunicationRecordRow,
    OAuthCredentialRow,
    OutboundDraftRow,
)
from job_apply_pro.storage.oauth_repository import OAuthRepository
from test_oauth_provider_connectivity import _oauth_client

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
PROVIDERS = [IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK]


def source_message(provider: IntegrationProvider) -> NormalizedMessage:
    return NormalizedMessage(
        provider=provider,
        provider_message_id="same-provider-message-id",
        provider_thread_id="same-thread-id",
        sender="Recruiter <recruiter@example.test>",
        recipients=["candidate@example.test"],
        subject="Exact source subject",
        body_text="Synthetic invitation",
        received_at=NOW,
        reply_headers=MailReplyHeaders(
            source_id_format="GMAIL"
            if provider is IntegrationProvider.GMAIL
            else "GRAPH_IMMUTABLE",
            from_address="recruiter@example.test",
            sender_address="recruiter@example.test",
            rfc_message_id="<parent@example.test>",
            references=("<ancestor@example.test>",),
        ),
    )


def mail_service(
    session: Session,
    provider: IntegrationProvider,
    *,
    identity: str | None = "account-a",
    epoch: str = "epoch-a",
    label: str = "candidate@example.test",
) -> tuple[CommunicationService, CommunicationRepository, FixtureMessageProvider]:
    repository = CommunicationRepository(session, SensitiveDataCipher(StaticKeyProvider(b"s" * 32)))
    adapter = FixtureMessageProvider(provider, [source_message(provider)])
    service = CommunicationService(
        repository,
        message_adapters={provider: adapter},
        provider_configs={
            provider: ProviderConnectionConfig(
                provider=provider,
                credential_reference=epoch,
                account_hint=label,
            )
        },
        provider_account_identities={provider: identity} if identity is not None else {},
    )
    return service, repository, adapter


def sync_source(service: CommunicationService, provider: IntegrationProvider) -> str:
    return service.sync_provider_messages(provider, since=None, workflows=[]).record_ids[0]


def reply_command(service: CommunicationService, record_id: str) -> DraftCreate:
    record = next(record for record in service.list_records() if record.id == record_id)
    assert record.reply_context
    return DraftCreate(
        mode=MailMode.REPLY,
        analysis_id=record_id,
        source_fingerprint=record.reply_context.fingerprint,
        body_text="Reviewed reply body",
        category=MessageCategory.INTERVIEW_REQUEST,
    )


@pytest.mark.parametrize("provider", PROVIDERS)
def test_trusted_sync_source_and_draft_are_immutable_encrypted_and_idempotent(
    session: Session, provider: IntegrationProvider
) -> None:
    service, repository, adapter = mail_service(session, provider)
    record_id = sync_source(service, provider)
    record = repository.get_record(record_id)
    assert record and record.reply_context
    context = record.reply_context
    assert context.source_record_id == record.id
    assert context.references == ("<ancestor@example.test>", "<parent@example.test>")
    assert context.subject == "Exact source subject"
    assert sync_source(service, provider) == record_id
    assert repository.get_record(record_id) == record
    draft = service.create_draft(reply_command(service, record_id))
    assert draft.recipient == context.recipient and draft.subject == context.subject
    assert draft.reply_context == context
    assert repository.get_draft(draft.id) == draft
    raw_record = session.get(CommunicationRecordRow, record_id)
    raw_draft = session.get(OutboundDraftRow, draft.id)
    assert raw_record and raw_draft
    for raw in (raw_record.encrypted_analysis, raw_draft.encrypted_payload):
        assert "recruiter@example.test" not in raw
        assert "<parent@example.test>" not in raw
        assert "Reviewed reply" not in raw
    confirmation = MutationConfirmation(
        fingerprint=draft.fingerprint,
        idempotency_key="one-reviewed-reply",
        confirmed_by="native-review",
    )
    accepted = service.send_draft(draft.id, confirmation)
    assert accepted.status is MutationStatus.ACCEPTED
    assert service.send_draft(draft.id, confirmation) == accepted
    assert len(adapter.sent) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("same_account", [False, True])
def test_reconnect_does_not_rebind_sources_or_drafts_and_manual_sync_creates_fresh_source(
    session: Session, provider: IntegrationProvider, same_account: bool
) -> None:
    old, repository, _ = mail_service(session, provider)
    old_id = sync_source(old, provider)
    old_record = repository.get_record(old_id)
    old_draft = old.create_draft(reply_command(old, old_id))
    current, _, adapter = mail_service(
        session, provider, identity="account-a" if same_account else "account-b", epoch="epoch-b"
    )
    hidden = current.list_records()[0]
    assert hidden.reply_context is None and hidden.reply_unavailable_reason
    with pytest.raises(ValueError, match="account changed"):
        current.create_draft(reply_command(old, old_id))
    with pytest.raises(ValueError, match="account changed"):
        current.send_draft(
            old_draft.id,
            MutationConfirmation(
                fingerprint=old_draft.fingerprint,
                idempotency_key="new-epoch-old-draft",
                confirmed_by="candidate",
            ),
        )
    new_id = sync_source(current, provider)
    assert new_id != old_id
    current.create_draft(reply_command(current, new_id))
    assert repository.get_record(old_id) == old_record
    assert repository.get_draft(old_draft.id) == old_draft
    assert len(repository.list_records()) == 2
    assert adapter.sent == []


@pytest.mark.parametrize("provider", PROVIDERS)
def test_public_analysis_cannot_bless_headers_or_poison_provider_sync(
    session: Session, provider: IntegrationProvider
) -> None:
    service, repository, _ = mail_service(session, provider)
    message = source_message(provider)
    app.dependency_overrides[get_communication_service] = lambda: service
    try:
        # The real analyze route also loads workflows; supply the existing in-memory session.
        from job_apply_pro.storage.database import get_session

        app.dependency_overrides[get_session] = lambda: session
        with TestClient(app) as api:
            forged = api.post(
                "/api/v1/communications/analyze",
                json={
                    **message.model_dump(mode="json"),
                    "reply_context": {"fingerprint": "a" * 64},
                    "source_account_key": "b" * 64,
                },
            )
            assert forged.status_code == 201
            assert forged.json()["reply_context"] is None
    finally:
        app.dependency_overrides.clear()
    manual = repository.list_records()[0]
    assert manual.source_account_key is None
    with pytest.raises(ValueError, match="provider-bound source"):
        service.create_draft(
            DraftCreate(
                mode=MailMode.REPLY,
                analysis_id=manual.id,
                source_fingerprint="a" * 64,
                body_text="Synthetic reply",
                category=MessageCategory.INTERVIEW_REQUEST,
            )
        )
    synced_id = sync_source(service, provider)
    assert synced_id != manual.id
    assert repository.get_record(manual.id) == manual
    assert repository.get_record(synced_id).reply_context is not None  # type: ignore[union-attr]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_missing_identity_source_remains_untrusted_even_after_identity_becomes_available(
    session: Session, provider: IntegrationProvider
) -> None:
    legacy, repository, _ = mail_service(session, provider, identity=None)
    old_id = sync_source(legacy, provider)
    before = repository.get_record(old_id)
    assert before and before.reply_context is None
    current, _, _ = mail_service(session, provider)
    new_id = sync_source(current, provider)
    assert new_id != old_id
    assert repository.get_record(old_id) == before
    assert current.create_draft(reply_command(current, new_id)).mode is MailMode.REPLY


@pytest.mark.parametrize(
    "override",
    [
        {"provider": "OUTLOOK"},
        {"recipient": "other@example.test"},
        {"subject": "Changed"},
        {"provider_thread_id": "other"},
        {"reply_context": {}},
        {"account_key": "a" * 64},
        {"headers": {"In-Reply-To": "<other@example.test>"}},
        {"policy": "AUTOMATIC"},
    ],
)
def test_reply_request_rejects_destination_account_header_and_policy_overrides(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        DraftCreate.model_validate(
            {
                "mode": "REPLY",
                "analysis_id": "record",
                "source_fingerprint": "a" * 64,
                "body_text": "Reviewed",
                "category": "INTERVIEW_REQUEST",
                **override,
            }
        )


def test_mode_is_mandatory_and_new_message_is_explicitly_unthreaded(session: Session) -> None:
    service, _, _ = mail_service(session, IntegrationProvider.GMAIL)
    record_id = sync_source(service, IntegrationProvider.GMAIL)
    command = {
        "analysis_id": record_id,
        "provider": "GMAIL",
        "recipient": "other@example.test",
        "subject": "Standalone subject",
        "body_text": "Reviewed",
        "category": "INTERVIEW_REQUEST",
    }
    with pytest.raises(ValidationError):
        DraftCreate.model_validate(command)
    draft = service.create_draft(DraftCreate.model_validate({**command, "mode": "NEW_MESSAGE"}))
    assert draft.reply_context is None and draft.provider_thread_id == ""
    assert draft.subject == "Standalone subject" and draft.recipient == "other@example.test"


def test_service_rejects_unreviewed_internal_command_before_draft_persistence(
    session: Session,
) -> None:
    service, repository, adapter = mail_service(session, IntegrationProvider.GMAIL)
    source_id = sync_source(service, IntegrationProvider.GMAIL)
    command = reply_command(service, source_id).model_copy(
        update={"policy": OutboundPolicy.AUTOMATIC}
    )
    with pytest.raises(ValueError, match="explicit review"):
        service.create_draft(command)
    assert repository.list_drafts() == []
    assert adapter.sent == []


def test_offline_preview_never_gains_send_authority_after_connecting(session: Session) -> None:
    provider = IntegrationProvider.GMAIL
    offline, repository, adapter = mail_service(session, provider, identity=None)
    source = offline.analyze_and_save(source_message(provider), [])
    command = DraftCreate(
        mode=MailMode.NEW_MESSAGE,
        analysis_id=source.id,
        provider=provider,
        recipient="recruiter@example.test",
        subject="Offline local preview",
        body_text="Reviewed draft",
        category=MessageCategory.INTERVIEW_REQUEST,
    )
    draft = offline.create_draft(command)
    assert draft.account_key is None and draft.account_label is None
    confirmation = MutationConfirmation(
        fingerprint=draft.fingerprint,
        idempotency_key="offline-preview-rejection",
        confirmed_by="native",
    )
    connected, _, current_adapter = mail_service(session, provider)
    for service in (offline, connected):
        with pytest.raises(ValueError, match="fresh account-bound draft"):
            service.send_draft(draft.id, confirmation)
    assert repository.get_draft(draft.id) == draft
    assert repository.list_audits() == []
    assert adapter.sent == current_adapter.sent == []
    fresh = connected.create_draft(command)
    assert fresh.id != draft.id and fresh.account_key is not None


def test_new_message_rejects_even_null_source_fingerprint() -> None:
    with pytest.raises(ValidationError):
        DraftCreate.model_validate(
            {
                "mode": "NEW_MESSAGE",
                "analysis_id": "record",
                "provider": "GMAIL",
                "recipient": "recruiter@example.test",
                "subject": "New",
                "body_text": "Body",
                "category": "INTERVIEW_REQUEST",
                "source_fingerprint": None,
            }
        )


@pytest.mark.parametrize("mutation", ["source", "context", "account", "recipient", "mode"])
def test_changed_review_never_reaches_adapter(
    session: Session, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    provider = IntegrationProvider.GMAIL
    service, repository, adapter = mail_service(session, provider)
    record_id = sync_source(service, provider)
    command = reply_command(service, record_id)
    draft = service.create_draft(command)
    if mutation == "source":
        record = repository.get_record(record_id)
        assert record
        monkeypatch.setattr(
            repository, "get_record", lambda _: record.model_copy(update={"reply_context": None})
        )
    else:
        updates: dict[str, dict[str, object]] = {
            "context": {"reply_context": None},
            "account": {"account_key": "f" * 64},
            "recipient": {"recipient": "other@example.test"},
            "mode": {"mode": MailMode.NEW_MESSAGE},
        }
        changed = draft.model_copy(update=updates[mutation])
        monkeypatch.setattr(repository, "get_draft", lambda _: changed)
    with pytest.raises(ValueError):
        service.send_draft(
            draft.id,
            MutationConfirmation(
                fingerprint=draft.fingerprint,
                idempotency_key="never-dispatch-changed",
                confirmed_by="native",
            ),
        )
    assert adapter.sent == [] and repository.list_audits() == []


def test_uncertain_reply_is_recorded_once_without_fallback(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository, adapter = mail_service(session, IntegrationProvider.OUTLOOK)
    draft = service.create_draft(
        reply_command(service, sync_source(service, IntegrationProvider.OUTLOOK))
    )
    calls = 0

    def uncertain(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise ProviderSendUncertainError()

    monkeypatch.setattr(adapter, "send", uncertain)
    confirmation = MutationConfirmation(
        fingerprint=draft.fingerprint, idempotency_key="uncertain-reply", confirmed_by="native"
    )
    first = service.send_draft(draft.id, confirmation)
    assert first.status is MutationStatus.UNCERTAIN
    assert service.send_draft(draft.id, confirmation) == first
    with pytest.raises(ValueError):
        service.send_draft(
            draft.id, confirmation.model_copy(update={"idempotency_key": "fresh-key"})
        )
    assert calls == 1 and len(repository.list_audits()) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("identity", [None, "provider-stable-identity"])
def test_oauth_profile_identity_is_encrypted_and_not_inferred_or_exposed(
    session: Session, provider: IntegrationProvider, identity: str | None
) -> None:
    requests: list[httpx.Request] = []

    def response(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"access_token": "synthetic-token", "expires_in": 3600})
        payload = (
            {"email": "candidate@example.test"}
            if provider is IntegrationProvider.GMAIL
            else {"mail": "candidate@example.test"}
        )
        if identity:
            payload["sub" if provider is IntegrationProvider.GMAIL else "id"] = identity
        return httpx.Response(200, json=payload)

    repository = OAuthRepository(session, SensitiveDataCipher(StaticKeyProvider(b"i" * 32)))
    config = _oauth_client(provider)
    oauth = OAuthConnectionService(
        repository,
        {provider: config},
        client=httpx.Client(transport=httpx.MockTransport(response)),
        now=lambda: NOW,
    )
    authorization = oauth.start(provider)
    completed = oauth.complete(code="synthetic-code", state=authorization.state)
    stored = repository.load_tokens(provider)
    assert stored and stored[1].account_identity == identity
    assert (
        "account_identity" not in completed.model_dump()
        and "account_identity" not in oauth.state(provider).model_dump()
    )
    row = session.scalar(select(OAuthCredentialRow))
    assert row and (identity is None or identity not in row.encrypted_token_set)
    assert stored[1].granted_scopes == sorted(config.requested_scopes)
    if provider is IntegrationProvider.OUTLOOK:
        assert requests[-1].url.params["$select"] == "id,mail,userPrincipalName"


@pytest.mark.parametrize("identity", [None, "provider-stable-identity"])
def test_refresh_retains_identity_and_epoch_without_profile_backfill(
    session: Session, identity: str | None
) -> None:
    provider = IntegrationProvider.GMAIL
    repository = OAuthRepository(session, SensitiveDataCipher(StaticKeyProvider(b"i" * 32)))
    repository.save_tokens(
        provider,
        "fixed-epoch",
        OAuthTokenSet(
            access_token=SecretStr("expired"),
            refresh_token=SecretStr("synthetic-refresh"),
            expires_at=NOW - timedelta(hours=1),
            granted_scopes=_oauth_client(provider).requested_scopes,
            account_hint="candidate@example.test",
            account_identity=identity,
        ),
        now=NOW,
    )
    requests: list[httpx.Request] = []

    def response(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST" and request.url.path == "/token"
        return httpx.Response(
            200, json={"access_token": "refreshed", "expires_in": 3600, "sub": "MUST-NOT-BLESS"}
        )

    oauth = OAuthConnectionService(
        repository,
        {provider: _oauth_client(provider)},
        client=httpx.Client(transport=httpx.MockTransport(response)),
        now=lambda: NOW,
    )
    assert oauth.access_token_bound(provider, "fixed-epoch") == "refreshed"
    stored = repository.load_tokens(provider)
    assert stored and stored[0] == "fixed-epoch" and stored[1].account_identity == identity
    assert len(requests) == 1
