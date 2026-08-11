from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

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
    ProviderNotConfiguredError,
    normalize_gmail_message,
    normalize_outlook_message,
)
from job_apply_pro.integrations.configuration import (
    CommunicationConfigurationError,
    build_communication_configuration,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.communications import CommunicationService
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.models import CommunicationRecordRow


def _service(
    session: Session,
    *,
    message_provider: FixtureMessageProvider | None = None,
    calendar_provider: FixtureCalendarProvider | None = None,
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
            '"automatic_categories":["APPLICATION_CONFIRMATION"]}'
        )
    )
    assert configuration.providers[0].credential_reference == "os-keychain:gmail:primary"
    assert configuration.automatic_categories == {MessageCategory.APPLICATION_CONFIRMATION}
    with pytest.raises(CommunicationConfigurationError):
        build_communication_configuration(
            SecretStr(
                '{"providers":[{"provider":"GMAIL",'
                '"credential_reference":"ref","access_token":"secret"}]}'
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
