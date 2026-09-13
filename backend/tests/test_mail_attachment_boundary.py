from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.communications import get_communication_service
from job_apply_pro.config import get_settings
from job_apply_pro.domain.communications import (
    DraftCreate,
    IntegrationProvider,
    MessageCategory,
    MutationConfirmation,
    MutationStatus,
    NormalizedMessage,
    OutboundDraft,
)
from job_apply_pro.integrations.communications import (
    DisabledMessageProvider,
    FixtureMessageProvider,
    UnsupportedMailAttachmentsError,
)
from job_apply_pro.integrations.provider_clients import (
    GmailMessageProvider,
    OutlookMessageProvider,
)
from job_apply_pro.main import create_app
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.communications import CommunicationService
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.database import get_session

ERROR = "Sending document attachments is not supported; no message was sent"
PRIVATE_VERSION = "private-candidate-resume-version"


def _command(
    provider: IntegrationProvider, *, analysis_id: str = "analysis-1", attachments: bool = True
) -> DraftCreate:
    return DraftCreate(
        analysis_id=analysis_id,
        provider=provider,
        provider_thread_id="thread-1",
        recipient="recruiter@example.test",
        subject="Reviewed response",
        body_text="Thank you for the invitation.",
        category=MessageCategory.INTERVIEW_REQUEST,
        document_version_ids=[PRIVATE_VERSION] if attachments else [],
    )


def _legacy_draft(command: DraftCreate) -> OutboundDraft:
    return OutboundDraft(
        id="legacy-draft-1",
        **command.model_dump(),
        fingerprint="a" * 64,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _confirmation(draft: OutboundDraft) -> MutationConfirmation:
    return MutationConfirmation(
        fingerprint=draft.fingerprint,
        idempotency_key="attachment-boundary-send-1",
        confirmed_by="candidate",
    )


def _service(
    session: Session, provider: IntegrationProvider
) -> tuple[CommunicationService, CommunicationRepository, FixtureMessageProvider, str]:
    repository = CommunicationRepository(session, SensitiveDataCipher(StaticKeyProvider(b"a" * 32)))
    adapter = FixtureMessageProvider(provider)
    service = CommunicationService(repository, message_adapters={provider: adapter})
    record = service.analyze_and_save(
        NormalizedMessage(
            provider=provider,
            provider_message_id="message-1",
            provider_thread_id="thread-1",
            sender="recruiter@example.test",
            recipients=["candidate@example.test"],
            subject="Interview invitation",
            body_text="Please share your availability.",
            received_at=datetime.now(UTC),
        ),
        [],
    )
    return service, repository, adapter, record.id


@pytest.mark.parametrize("provider", [IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK])
def test_attachment_draft_rejected_before_repository_or_document_lookup(
    provider: IntegrationProvider,
) -> None:
    with pytest.raises(UnsupportedMailAttachmentsError) as error:
        CommunicationService().create_draft(_command(provider))
    assert str(error.value) == ERROR
    assert PRIVATE_VERSION not in str(error.value)


@pytest.mark.parametrize("provider", [IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK])
def test_legacy_attachment_draft_fails_before_adapter_and_keeps_idempotent_failed_audit(
    session: Session, provider: IntegrationProvider
) -> None:
    service, repository, adapter, analysis_id = _service(session, provider)
    draft = repository.save_draft(_legacy_draft(_command(provider, analysis_id=analysis_id)))
    confirmation = _confirmation(draft)

    with pytest.raises(UnsupportedMailAttachmentsError) as error:
        service.send_draft(draft.id, confirmation)

    assert str(error.value) == ERROR
    assert adapter.sent == []
    audits = service.list_audits()
    assert len(audits) == 1
    assert audits[0].status is MutationStatus.FAILED
    assert audits[0].error_code == "UnsupportedMailAttachmentsError"
    assert audits[0].provider_resource_id is None
    assert PRIVATE_VERSION not in audits[0].model_dump_json()
    assert service.send_draft(draft.id, confirmation) == audits[0]
    assert adapter.sent == []
    assert len(service.list_audits()) == 1


def test_stale_approval_remains_rejected_before_attachment_audit(session: Session) -> None:
    service, repository, adapter, analysis_id = _service(session, IntegrationProvider.GMAIL)
    draft = repository.save_draft(
        _legacy_draft(_command(IntegrationProvider.GMAIL, analysis_id=analysis_id))
    )
    confirmation = _confirmation(draft).model_copy(update={"fingerprint": "b" * 64})
    with pytest.raises(ValueError, match="Draft changed after review"):
        service.send_draft(draft.id, confirmation)
    assert service.list_audits() == []
    assert adapter.sent == []


@pytest.mark.parametrize("recorded_status", [MutationStatus.ACCEPTED, MutationStatus.CONFIRMED])
def test_prior_recorded_replay_is_not_rewritten_or_resent(
    session: Session, monkeypatch: pytest.MonkeyPatch, recorded_status: MutationStatus
) -> None:
    service, repository, adapter, analysis_id = _service(session, IntegrationProvider.GMAIL)
    draft = service.create_draft(
        _command(IntegrationProvider.GMAIL, analysis_id=analysis_id, attachments=False)
    )
    confirmation = _confirmation(draft)
    confirmed = service.send_draft(draft.id, confirmation)
    confirmed = repository.add_audit(confirmed.model_copy(update={"status": recorded_status}))
    monkeypatch.setattr(
        repository,
        "get_draft",
        lambda draft_id: draft.model_copy(update={"document_version_ids": [PRIVATE_VERSION]}),
    )

    assert service.send_draft(draft.id, confirmation) == confirmed
    assert confirmed.status is recorded_status
    assert adapter.sent == [(draft.id, confirmation.idempotency_key)]
    assert len(service.list_audits()) == 1


class _NoTokens:
    def access_token(self, provider: IntegrationProvider) -> str:
        raise AssertionError("Attachment rejection must precede token access")


@pytest.mark.parametrize("provider", [IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK])
def test_direct_provider_rejects_attachments_before_credentials_or_http(
    provider: IntegrationProvider,
) -> None:
    requests: list[httpx.Request] = []

    def forbidden(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("Attachment rejection must precede provider requests")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        adapter = (
            GmailMessageProvider(_NoTokens(), client=client)
            if provider is IntegrationProvider.GMAIL
            else OutlookMessageProvider(_NoTokens(), client=client)
        )
        with pytest.raises(UnsupportedMailAttachmentsError) as error:
            adapter.send(_legacy_draft(_command(provider)), idempotency_key="send-direct-1")
    assert str(error.value) == ERROR
    assert requests == []


@pytest.mark.parametrize("adapter_type", [FixtureMessageProvider, DisabledMessageProvider])
def test_non_network_adapters_preserve_attachment_rejection(
    adapter_type: type[FixtureMessageProvider] | type[DisabledMessageProvider],
) -> None:
    adapter = adapter_type(IntegrationProvider.GMAIL)
    with pytest.raises(UnsupportedMailAttachmentsError, match="no message was sent"):
        adapter.send(
            _legacy_draft(_command(IntegrationProvider.GMAIL)), idempotency_key="send-direct-2"
        )
    if isinstance(adapter, FixtureMessageProvider):
        assert adapter.sent == []


def test_api_rejects_new_and_legacy_attachment_drafts_without_private_details(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository, adapter, analysis_id = _service(session, IntegrationProvider.GMAIL)
    command = _command(IntegrationProvider.GMAIL, analysis_id=analysis_id)
    draft = repository.save_draft(_legacy_draft(command))
    monkeypatch.setenv("JAP_API_TOKEN", "attachment-boundary-test-token")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_communication_service] = lambda: service
    app.dependency_overrides[get_session] = lambda: session
    headers = {"X-Job-Apply-Pro-Token": "attachment-boundary-test-token"}
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/communications/drafts",
                json=command.model_dump(mode="json"),
                headers=headers,
            )
            assert created.status_code == 422
            assert created.json() == {"detail": ERROR}
            assert len(service.list_drafts()) == 1
            assert service.list_audits() == []
            sent = client.post(
                f"/api/v1/communications/drafts/{draft.id}/send",
                json=_confirmation(draft).model_dump(mode="json"),
                headers=headers,
            )
            assert sent.status_code == 409
            assert sent.json() == {"detail": ERROR}
            assert PRIVATE_VERSION not in sent.text
            assert service.list_audits()[0].status is MutationStatus.FAILED
            assert adapter.sent == []
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
