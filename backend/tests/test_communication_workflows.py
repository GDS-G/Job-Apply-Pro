import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.communications import get_communication_service
from job_apply_pro.config import get_settings
from job_apply_pro.domain.communications import (
    CalendarEventSnapshot,
    CalendarMutationCreate,
    DraftCreate,
    FollowUpCreate,
    IntegrationProvider,
    MessageCategory,
    MutationConfirmation,
    MutationStatus,
    NormalizedMessage,
)
from job_apply_pro.domain.workbench import WorkflowRunSnapshot
from job_apply_pro.domain.workflow import WorkflowState
from job_apply_pro.integrations.communications import (
    CalendarProviderAdapter,
    FixtureCalendarProvider,
    FixtureMessageProvider,
    MessageProviderAdapter,
    ProviderMutationError,
    ProviderNotConfiguredError,
    normalize_gmail_message,
    normalize_outlook_message,
)
from job_apply_pro.integrations.configuration import (
    CommunicationConfigurationError,
    ProviderConnectionConfig,
    build_communication_configuration,
)
from job_apply_pro.main import create_app
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.communications import CommunicationService
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.models import (
    CommunicationRecordRow,
    ProviderCalendarEventRow,
    ProviderSyncStateRow,
)


def _service(
    session: Session,
    *,
    message_provider: FixtureMessageProvider | None = None,
    calendar_provider: FixtureCalendarProvider | None = None,
    provider_configs: dict[IntegrationProvider, ProviderConnectionConfig] | None = None,
) -> CommunicationService:
    repository = CommunicationRepository(session, SensitiveDataCipher(StaticKeyProvider(b"c" * 32)))
    message_adapters: dict[IntegrationProvider, MessageProviderAdapter] | None = (
        {IntegrationProvider.GMAIL: message_provider} if message_provider is not None else None
    )
    calendar_adapters: dict[IntegrationProvider, CalendarProviderAdapter] | None = (
        {IntegrationProvider.GOOGLE_CALENDAR: calendar_provider}
        if calendar_provider is not None
        else None
    )
    return CommunicationService(
        repository,
        message_adapters=message_adapters,
        calendar_adapters=calendar_adapters,
        provider_configs=provider_configs,
    )


def _message() -> NormalizedMessage:
    return NormalizedMessage(
        provider=IntegrationProvider.GMAIL,
        provider_message_id="gmail-message-1",
        provider_thread_id="gmail-thread-1",
        sender="recruiter@example.test",
        recipients=["candidate@example.test"],
        subject="Interview availability",
        body_text="Please schedule an interview and share your availability.",
        received_at=datetime(2026, 8, 5, 15, tzinfo=UTC),
    )


def test_provider_fixtures_normalize_to_common_message_contract() -> None:
    gmail = normalize_gmail_message(
        {
            "id": "g-1",
            "threadId": "gt-1",
            "from": "recruiter@example.test",
            "to": ["candidate@example.test"],
            "subject": "Interview",
            "text": "Choose a time",
            "receivedAt": "2026-08-05T15:00:00+00:00",
            "attachments": ["agenda.pdf"],
        }
    )
    outlook = normalize_outlook_message(
        {
            "id": "o-1",
            "conversationId": "ot-1",
            "sender": {"address": "recruiter@example.test"},
            "toRecipients": [{"address": "candidate@example.test"}],
            "subject": "Interview",
            "bodyPreview": "Choose a time",
            "receivedDateTime": "2026-08-05T15:00:00+00:00",
            "attachments": [{"name": "agenda.pdf"}],
        }
    )
    assert gmail.provider is IntegrationProvider.GMAIL
    assert outlook.provider is IntegrationProvider.OUTLOOK
    assert gmail.attachment_names == outlook.attachment_names == ["agenda.pdf"]


def test_communication_configuration_accepts_references_and_rejects_tokens() -> None:
    configuration = build_communication_configuration(
        SecretStr(
            '{"providers":[{"provider":"GMAIL",'
            '"credential_reference":"os-keychain:gmail:primary"}],'
            '"oauth_clients":[{"provider":"GMAIL",'
            '"client_id":"public-desktop-client",'
            '"requested_scopes":["openid","email"]}],'
            '"automatic_categories":["APPLICATION_CONFIRMATION"]}'
        )
    )
    assert configuration.providers[0].credential_reference == "os-keychain:gmail:primary"
    assert configuration.oauth_clients[0].client_id == "public-desktop-client"
    assert configuration.automatic_categories == {MessageCategory.APPLICATION_CONFIRMATION}
    with pytest.raises(CommunicationConfigurationError):
        build_communication_configuration(
            SecretStr(
                '{"providers":[{"provider":"GMAIL",'
                '"credential_reference":"ref","access_token":"secret"}]}'
            )
        )
    with pytest.raises(CommunicationConfigurationError):
        build_communication_configuration(
            SecretStr(
                '{"oauth_clients":[{"provider":"GMAIL",'
                '"client_id":"public-desktop-client",'
                '"redirect_uri":"https://attacker.example.test/callback",'
                '"requested_scopes":["openid"]}]}'
            )
        )
    with pytest.raises(CommunicationConfigurationError):
        build_communication_configuration(
            SecretStr(
                '{"oauth_clients":[{"provider":"GMAIL",'
                '"client_id":"public-desktop-client",'
                '"client_secret":"must-not-be-accepted",'
                '"requested_scopes":["openid"]}]}'
            )
        )


def test_analysis_and_draft_payloads_are_encrypted_at_rest(session: Session) -> None:
    service = _service(session)
    workflow = WorkflowRunSnapshot(
        workflow_id="workflow-1",
        application_id="application-1",
        profile_id="profile-1",
        candidate_display_name="Candidate",
        employer="Example",
        title="Platform Engineer",
        state=WorkflowState.TRACKING_ACTIVE,
        progress=100,
        updated_at=datetime.now(UTC),
        events=[],
    )
    record = service.analyze_and_save(_message(), [workflow])
    stored = session.scalar(select(CommunicationRecordRow))
    assert stored is not None
    assert "Interview availability" not in stored.encrypted_analysis
    assert stored.encrypted_analysis.startswith("jap:v1:test-v1:")
    listed = service.list_records()
    assert listed == [record]
    assert service.tracking_statuses()[0].workflow_id == workflow.workflow_id


def test_provider_message_sync_imports_once_and_reports_duplicates(session: Session) -> None:
    adapter = FixtureMessageProvider(IntegrationProvider.GMAIL, [_message()])
    service = _service(session, message_provider=adapter)

    first = service.sync_provider_messages(
        IntegrationProvider.GMAIL,
        since=datetime(2026, 8, 1, tzinfo=UTC),
        workflows=[],
    )
    second = service.sync_provider_messages(
        IntegrationProvider.GMAIL,
        since=None,
        workflows=[],
    )

    assert first.fetched_count == first.imported_count == 1
    assert first.duplicate_count == 0
    assert first.sync_mode.value == "INITIAL"
    assert second.fetched_count == second.duplicate_count == 1
    assert second.imported_count == 0
    assert second.sync_mode.value == "INCREMENTAL"
    assert second.record_ids == first.record_ids
    sync_state = session.get(ProviderSyncStateRow, IntegrationProvider.GMAIL.value)
    assert sync_state is not None
    assert "fixture-cursor" not in sync_state.encrypted_cursor
    assert sync_state.encrypted_cursor.startswith("jap:v1:test-v1:")
    with pytest.raises(ValueError, match="mail provider"):
        service.sync_provider_messages(
            IntegrationProvider.GOOGLE_CALENDAR,
            since=None,
            workflows=[],
        )


def test_provider_sync_cursor_advances_only_after_import_and_is_account_bound(
    session: Session,
) -> None:
    wrong_account_message = _message().model_copy(update={"provider": IntegrationProvider.OUTLOOK})
    failing_adapter = FixtureMessageProvider(IntegrationProvider.GMAIL, [wrong_account_message])
    failing_service = _service(session, message_provider=failing_adapter)
    with pytest.raises(ProviderMutationError, match="wrong account type"):
        failing_service.sync_provider_messages(IntegrationProvider.GMAIL, since=None, workflows=[])
    assert session.get(ProviderSyncStateRow, IntegrationProvider.GMAIL.value) is None

    repository = CommunicationRepository(session, SensitiveDataCipher(StaticKeyProvider(b"c" * 32)))
    adapter = FixtureMessageProvider(IntegrationProvider.GMAIL, [_message()])
    first_service = CommunicationService(
        repository,
        message_adapters={IntegrationProvider.GMAIL: adapter},
        provider_configs={
            IntegrationProvider.GMAIL: ProviderConnectionConfig(
                provider=IntegrationProvider.GMAIL,
                credential_reference="oauth:gmail:first",
            )
        },
    )
    second_service = CommunicationService(
        repository,
        message_adapters={IntegrationProvider.GMAIL: adapter},
        provider_configs={
            IntegrationProvider.GMAIL: ProviderConnectionConfig(
                provider=IntegrationProvider.GMAIL,
                credential_reference="oauth:gmail:second",
            )
        },
    )

    assert (
        first_service.sync_provider_messages(
            IntegrationProvider.GMAIL, since=None, workflows=[]
        ).sync_mode.value
        == "INITIAL"
    )
    assert (
        second_service.sync_provider_messages(
            IntegrationProvider.GMAIL, since=None, workflows=[]
        ).sync_mode.value
        == "INITIAL"
    )
    second_binding = hashlib.sha256(b"GMAIL\0oauth:gmail:second\0").hexdigest()
    current_state = repository.get_sync_state(IntegrationProvider.GMAIL, second_binding)
    assert current_state is not None
    stale_result = repository.save_sync_state(
        IntegrationProvider.GMAIL,
        SecretStr("stale-concurrent-cursor"),
        second_binding,
        None,
    )
    assert stale_result.cursor.get_secret_value() == current_state.cursor.get_secret_value()


def test_provider_message_sync_api_returns_sanitized_counts(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(
        session,
        message_provider=FixtureMessageProvider(IntegrationProvider.GMAIL, [_message()]),
    )
    monkeypatch.setenv("JAP_API_TOKEN", "provider-sync-token")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_communication_service] = lambda: service
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/communications/providers/GMAIL/messages/sync",
            headers={"X-Job-Apply-Pro-Token": "provider-sync-token"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "provider": "GMAIL",
            "fetched_count": 1,
            "imported_count": 1,
            "duplicate_count": 0,
            "record_ids": response.json()["record_ids"],
            "sync_mode": "INITIAL",
            "cursor_updated_at": response.json()["cursor_updated_at"],
        }
        assert len(response.json()["record_ids"]) == 1
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_calendar_sync_reconciles_encrypted_local_snapshot(session: Session) -> None:
    anchor = datetime(2026, 8, 11, 16, tzinfo=UTC)
    first_event = CalendarEventSnapshot(
        provider_event_id="calendar-1",
        title="Technical interview with Private Employer",
        start_at=anchor + timedelta(days=1),
        end_at=anchor + timedelta(days=1, hours=1),
        time_zone="UTC",
        attendees=["candidate@example.test"],
        conferencing_url="https://meet.example.test/private",
    )
    stale_event = CalendarEventSnapshot(
        provider_event_id="calendar-stale",
        title="Recruiter call",
        start_at=anchor + timedelta(days=2),
        end_at=anchor + timedelta(days=2, hours=1),
        time_zone="UTC",
    )
    adapter = FixtureCalendarProvider(
        IntegrationProvider.GOOGLE_CALENDAR,
        [first_event, stale_event],
    )
    service = _service(session, calendar_provider=adapter)

    initial = service.sync_provider_calendar(IntegrationProvider.GOOGLE_CALENDAR, now=anchor)
    adapter.events = [first_event.model_copy(update={"title": "Updated technical interview"})]
    reconciled = service.sync_provider_calendar(IntegrationProvider.GOOGLE_CALENDAR, now=anchor)
    stored = service.list_synced_calendar_events(now=anchor)

    assert initial.fetched_count == initial.stored_count == 2
    assert initial.removed_count == 0
    assert reconciled.fetched_count == reconciled.stored_count == 1
    assert reconciled.removed_count == 1
    assert [item.event.title for item in stored] == ["Updated technical interview"]
    rows = session.scalars(select(ProviderCalendarEventRow)).all()
    assert len(rows) == 1
    assert "Updated technical interview" not in rows[0].encrypted_event


def test_calendar_snapshot_is_hidden_after_account_binding_changes(session: Session) -> None:
    anchor = datetime(2026, 8, 11, 16, tzinfo=UTC)
    adapter = FixtureCalendarProvider(
        IntegrationProvider.GOOGLE_CALENDAR,
        [
            CalendarEventSnapshot(
                provider_event_id="calendar-account-bound",
                title="Interview",
                start_at=anchor + timedelta(days=1),
                end_at=anchor + timedelta(days=1, hours=1),
                time_zone="UTC",
            )
        ],
    )
    first = _service(
        session,
        calendar_provider=adapter,
        provider_configs={
            IntegrationProvider.GOOGLE_CALENDAR: ProviderConnectionConfig(
                provider=IntegrationProvider.GOOGLE_CALENDAR,
                credential_reference="oauth:google-calendar:first",
                account_hint="first@example.test",
            )
        },
    )
    first.sync_provider_calendar(IntegrationProvider.GOOGLE_CALENDAR, now=anchor)
    assert len(first.list_synced_calendar_events(now=anchor)) == 1

    second = _service(
        session,
        calendar_provider=adapter,
        provider_configs={
            IntegrationProvider.GOOGLE_CALENDAR: ProviderConnectionConfig(
                provider=IntegrationProvider.GOOGLE_CALENDAR,
                credential_reference="oauth:google-calendar:second",
                account_hint="second@example.test",
            )
        },
    )
    assert second.list_synced_calendar_events(now=anchor) == []


def test_calendar_sync_api_returns_only_sanitized_counts(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchor = datetime.now(UTC).replace(microsecond=0)
    adapter = FixtureCalendarProvider(
        IntegrationProvider.GOOGLE_CALENDAR,
        [
            CalendarEventSnapshot(
                provider_event_id="calendar-private-id",
                title="Interview with Private Employer",
                start_at=anchor + timedelta(days=1),
                end_at=anchor + timedelta(days=1, hours=1),
                time_zone="UTC",
                attendees=["candidate@example.test"],
            )
        ],
    )
    service = _service(session, calendar_provider=adapter)
    monkeypatch.setenv("JAP_API_TOKEN", "calendar-sync-token")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_communication_service] = lambda: service
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/communications/providers/GOOGLE_CALENDAR/calendar/sync",
            headers={"X-Job-Apply-Pro-Token": "calendar-sync-token"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["provider"] == "GOOGLE_CALENDAR"
        assert payload["fetched_count"] == payload["stored_count"] == 1
        assert payload["removed_count"] == 0
        assert "calendar-private-id" not in response.text
        assert "Private Employer" not in response.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_fingerprinted_send_is_audited_and_idempotent(session: Session) -> None:
    adapter = FixtureMessageProvider(IntegrationProvider.GMAIL)
    service = _service(session, message_provider=adapter)
    record = service.analyze_and_save(_message(), [])
    draft = service.create_draft(
        DraftCreate(
            analysis_id=record.id,
            provider=IntegrationProvider.GMAIL,
            provider_thread_id="gmail-thread-1",
            recipient="recruiter@example.test",
            subject="Re: Interview availability",
            body_text="Thank you. I am available Thursday at 10:00 UTC.",
            category=MessageCategory.INTERVIEW_REQUEST,
            document_version_ids=["resume-version-4"],
        )
    )
    command = MutationConfirmation(
        fingerprint=draft.fingerprint,
        idempotency_key="send-interview-response-0001",
        confirmed_by="candidate",
    )
    first = service.send_draft(draft.id, command)
    replay = service.send_draft(draft.id, command)
    assert first.status is MutationStatus.CONFIRMED
    assert first.provider_resource_id == "fixture-message-1"
    assert replay == first
    assert adapter.sent == [(draft.id, command.idempotency_key)]


def test_disabled_send_fails_closed_and_keeps_failed_audit(session: Session) -> None:
    service = _service(session)
    record = service.analyze_and_save(_message(), [])
    draft = service.create_draft(
        DraftCreate(
            analysis_id=record.id,
            provider=IntegrationProvider.GMAIL,
            provider_thread_id="gmail-thread-1",
            recipient="recruiter@example.test",
            subject="Re: Interview",
            body_text="Thank you for reaching out.",
            category=MessageCategory.INTERVIEW_REQUEST,
        )
    )
    with pytest.raises(ProviderNotConfiguredError):
        service.send_draft(
            draft.id,
            MutationConfirmation(
                fingerprint=draft.fingerprint,
                idempotency_key="disabled-send-0001",
                confirmed_by="candidate",
            ),
        )
    assert service.list_audits()[0].status is MutationStatus.FAILED


def test_calendar_mutation_and_follow_up_are_audited_and_deduplicated(
    session: Session,
) -> None:
    adapter = FixtureCalendarProvider(IntegrationProvider.GOOGLE_CALENDAR)
    service = _service(session, calendar_provider=adapter)
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=30)
    plan = service.plan_calendar_mutation(
        CalendarMutationCreate(
            provider=IntegrationProvider.GOOGLE_CALENDAR,
            workflow_id="workflow-1",
            event=CalendarEventSnapshot(
                provider_event_id="local-interview-1",
                title="Interview with Example Co",
                start_at=start,
                end_at=start + timedelta(hours=1),
                time_zone="UTC",
                attendees=["candidate@example.test", "recruiter@example.test"],
                conferencing_url="https://meet.example.test/sanitized",
            ),
        )
    )
    audit = service.execute_calendar_mutation(
        plan.id,
        MutationConfirmation(
            fingerprint=plan.fingerprint,
            idempotency_key="calendar-interview-0001",
            confirmed_by="candidate",
        ),
    )
    follow_up_command = FollowUpCreate(
        workflow_id="workflow-1",
        reason="Send interview thank-you",
        due_at=start + timedelta(days=1),
        channel=IntegrationProvider.GMAIL,
    )
    first = service.schedule_follow_up(follow_up_command)
    duplicate = service.schedule_follow_up(follow_up_command)
    assert audit.status is MutationStatus.CONFIRMED
    assert audit.provider_resource_id == "fixture-event-1"
    assert first == duplicate
    summary = service.daily_summary()
    assert summary.confirmed_mutations == 1
    assert summary.scheduled_follow_ups == 1
    assert summary.due_follow_ups == 0
