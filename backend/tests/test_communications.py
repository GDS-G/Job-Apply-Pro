from datetime import UTC, datetime, timedelta

from job_apply_pro.domain.communications import (
    AttachmentCandidate,
    CalendarEventSnapshot,
    IntegrationProvider,
    IntegrationStatus,
    MessageCategory,
    NormalizedMessage,
    SchedulingRequest,
)
from job_apply_pro.domain.workbench import WorkflowRunSnapshot
from job_apply_pro.domain.workflow import WorkflowState
from job_apply_pro.services.communications import CommunicationService


def _message() -> NormalizedMessage:
    return NormalizedMessage(
        provider=IntegrationProvider.OUTLOOK,
        provider_message_id="message-1",
        provider_thread_id="thread-1",
        sender="recruiter@acme.example",
        recipients=["candidate@example.com"],
        subject="Acme interview availability",
        body_text="We would like to schedule an interview for the Platform Engineer role.",
        received_at=datetime.now(UTC),
    )


def test_classification_correlation_and_review_only_reply() -> None:
    service = CommunicationService()
    message = _message()
    classification = service.classify(message)
    assert classification.category is MessageCategory.INTERVIEW_REQUEST
    workflow = WorkflowRunSnapshot(
        workflow_id="workflow-1",
        application_id="application-1",
        profile_id="profile-1",
        candidate_display_name="Candidate",
        employer="Acme",
        title="Platform Engineer",
        state=WorkflowState.TRACKING_ACTIVE,
        progress=100,
        updated_at=datetime.now(UTC),
        events=[],
    )
    correlation = service.correlate(message, [workflow])
    assert correlation.workflow_id == workflow.workflow_id
    assert correlation.confidence == 1
    draft = service.draft_reply(message, classification)
    assert draft.requires_review
    assert not draft.auto_send_allowed
    assert draft.evidence == [message.provider_message_id]


def test_calendar_ranking_detects_conflicts_and_working_hours() -> None:
    service = CommunicationService()
    base = datetime(2026, 8, 6, 9, tzinfo=UTC)
    events = [
        CalendarEventSnapshot(
            provider_event_id="busy",
            title="Existing event",
            start_at=base,
            end_at=base + timedelta(hours=1),
            time_zone="UTC",
        )
    ]
    ranked = service.rank_times(
        SchedulingRequest(
            proposed_starts=[base, base + timedelta(hours=2), base - timedelta(hours=3)],
            duration_minutes=60,
            time_zone="UTC",
        ),
        events,
    )
    assert ranked[0].available
    assert ranked[0].start_at == base + timedelta(hours=2)
    assert {conflict for item in ranked for conflict in item.conflicts} == {
        "busy",
        "OUTSIDE_WORKING_HOURS",
    }


def test_integrations_are_disabled_until_oauth_configuration() -> None:
    health = CommunicationService().health()
    assert {item.provider for item in health} == set(IntegrationProvider)
    assert all(item.status is IntegrationStatus.NOT_CONFIGURED for item in health)
    assert all(not item.read_enabled and not item.write_enabled for item in health)


def test_attachment_verification_binds_profile_version_type_and_size() -> None:
    candidate = AttachmentCandidate(
        profile_id="profile-1",
        document_version_id="version-1",
        file_name="resume.pdf",
        media_type="application/pdf",
        size_bytes=2048,
    )
    approved = CommunicationService().verify_attachment(candidate, expected_profile_id="profile-1")
    assert approved.approved
    rejected = CommunicationService().verify_attachment(
        candidate.model_copy(update={"profile_id": "other", "file_name": "resume.exe"}),
        expected_profile_id="profile-1",
    )
    assert not rejected.approved
    assert rejected.reasons == ["PROFILE_MISMATCH", "UNEXPECTED_FILE_EXTENSION"]
