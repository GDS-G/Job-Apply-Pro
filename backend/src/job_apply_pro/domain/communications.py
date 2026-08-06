from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IntegrationProvider(StrEnum):
    GMAIL = "GMAIL"
    OUTLOOK = "OUTLOOK"
    GOOGLE_CALENDAR = "GOOGLE_CALENDAR"
    OUTLOOK_CALENDAR = "OUTLOOK_CALENDAR"


class IntegrationStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


class OutboundPolicy(StrEnum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    AUTOMATIC = "AUTOMATIC"


class MutationKind(StrEnum):
    SEND_MESSAGE = "SEND_MESSAGE"
    CREATE_CALENDAR_EVENT = "CREATE_CALENDAR_EVENT"
    UPDATE_CALENDAR_EVENT = "UPDATE_CALENDAR_EVENT"


class MutationStatus(StrEnum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class FollowUpStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ApplicationCommunicationStage(StrEnum):
    SUBMITTED = "SUBMITTED"
    RECRUITER_CONTACT = "RECRUITER_CONTACT"
    SCREENING = "SCREENING"
    INTERVIEW = "INTERVIEW"
    ASSESSMENT = "ASSESSMENT"
    REJECTED = "REJECTED"
    OFFER = "OFFER"


class MessageCategory(StrEnum):
    RECRUITER_INQUIRY = "RECRUITER_INQUIRY"
    INTERVIEW_REQUEST = "INTERVIEW_REQUEST"
    SCREENING_REQUEST = "SCREENING_REQUEST"
    ASSESSMENT_INVITATION = "ASSESSMENT_INVITATION"
    APPLICATION_CONFIRMATION = "APPLICATION_CONFIRMATION"
    STATUS_UPDATE = "STATUS_UPDATE"
    REJECTION = "REJECTION"
    OFFER = "OFFER"
    JOB_ALERT = "JOB_ALERT"
    NEWSLETTER = "NEWSLETTER"
    SPAM_OR_UNRELATED = "SPAM_OR_UNRELATED"


class NormalizedMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: IntegrationProvider
    provider_message_id: str = Field(min_length=1, max_length=500)
    provider_thread_id: str = Field(min_length=1, max_length=500)
    sender: str = Field(min_length=1, max_length=500)
    recipients: list[str] = Field(default_factory=list, max_length=100)
    subject: str = Field(max_length=1_000)
    body_text: str = Field(max_length=100_000)
    received_at: datetime
    attachment_names: list[str] = Field(default_factory=list, max_length=100)
    referenced_identifiers: list[str] = Field(default_factory=list, max_length=100)
    referenced_urls: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("received_at")
    @classmethod
    def require_received_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must include a UTC offset")
        return value


class MessageClassification(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: MessageCategory
    confidence: float = Field(ge=0, le=1)
    matched_signals: list[str]
    requires_review: bool


class CommunicationAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    message: NormalizedMessage
    classification: MessageClassification
    correlation: "ApplicationCorrelation"
    reply_draft: "ReplyDraft"
    proposed_times: list[datetime] = Field(default_factory=list, max_length=50)
    time_proposal_requires_review: bool = True


class ApplicationCorrelation(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    matched_signals: list[str]
    requires_review: bool


class ReplyDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject: str = Field(min_length=1, max_length=1_000)
    body_text: str = Field(min_length=1, max_length=20_000)
    category: MessageCategory
    requires_review: bool = True
    auto_send_allowed: bool = False
    evidence: list[str] = Field(default_factory=list, max_length=100)


class AttachmentCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str = Field(min_length=1, max_length=100)
    document_version_id: str = Field(min_length=1, max_length=100)
    file_name: str = Field(min_length=1, max_length=500)
    media_type: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=0, le=100_000_000)


class AttachmentVerification(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_version_id: str
    approved: bool
    reasons: list[str]


class CalendarEventSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_event_id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=1_000)
    start_at: datetime
    end_at: datetime
    time_zone: str = Field(min_length=1, max_length=100)
    attendees: list[str] = Field(default_factory=list, max_length=100)
    conferencing_url: str | None = Field(default=None, max_length=2_000)
    location: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_interval(self) -> "CalendarEventSnapshot":
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.start_at, self.end_at)
        ):
            raise ValueError("calendar event timestamps must include UTC offsets")
        if self.end_at <= self.start_at:
            raise ValueError("calendar event end_at must be after start_at")
        return self


class SchedulingRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposed_starts: list[datetime] = Field(min_length=1, max_length=50)
    duration_minutes: int = Field(ge=15, le=480)
    time_zone: str = Field(min_length=1, max_length=100)
    working_hour_start: int = Field(default=8, ge=0, le=23)
    working_hour_end: int = Field(default=18, ge=1, le=24)

    @model_validator(mode="after")
    def validate_schedule(self) -> "SchedulingRequest":
        if self.working_hour_end <= self.working_hour_start:
            raise ValueError("working_hour_end must be after working_hour_start")
        if any(value.tzinfo is None or value.utcoffset() is None for value in self.proposed_starts):
            raise ValueError("proposed start times must include UTC offsets")
        return self


class SchedulingPlanRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: SchedulingRequest
    events: list[CalendarEventSnapshot] = Field(default_factory=list, max_length=1_000)


class SchedulingRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_at: datetime
    end_at: datetime
    time_zone: str
    conflicts: list[str]
    rank: int = Field(ge=1)
    available: bool


class IntegrationHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: IntegrationProvider
    status: IntegrationStatus
    message: str
    read_enabled: bool = False
    write_enabled: bool = False
    credential_reference: str | None = Field(default=None, max_length=200)


class OAuthAuthorizationState(BaseModel):
    """Non-secret OAuth state safe to cross the renderer boundary."""

    model_config = ConfigDict(frozen=True)

    provider: IntegrationProvider
    status: IntegrationStatus
    credential_reference: str | None = Field(default=None, max_length=200)
    granted_scopes: list[str] = Field(default_factory=list, max_length=100)
    expires_at: datetime | None = None
    account_hint: str | None = Field(default=None, max_length=200)


class CommunicationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=100)
    analysis: CommunicationAnalysis
    received_at: datetime
    created_at: datetime


class DraftCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str = Field(min_length=1, max_length=100)
    workflow_id: str | None = Field(default=None, max_length=100)
    provider: IntegrationProvider
    provider_thread_id: str = Field(min_length=1, max_length=500)
    recipient: str = Field(min_length=1, max_length=500)
    subject: str = Field(min_length=1, max_length=1_000)
    body_text: str = Field(min_length=1, max_length=20_000)
    category: MessageCategory
    policy: OutboundPolicy = OutboundPolicy.REVIEW_REQUIRED
    document_version_ids: list[str] = Field(default_factory=list, max_length=20)


class OutboundDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=100)
    analysis_id: str
    workflow_id: str | None = None
    provider: IntegrationProvider
    provider_thread_id: str
    recipient: str
    subject: str
    body_text: str
    category: MessageCategory
    policy: OutboundPolicy
    document_version_ids: list[str]
    fingerprint: str = Field(min_length=64, max_length=64)
    created_at: datetime
    updated_at: datetime


class MutationConfirmation(BaseModel):
    model_config = ConfigDict(frozen=True)

    fingerprint: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=200)
    confirmed_by: str = Field(min_length=1, max_length=200)


class MutationAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=100)
    kind: MutationKind
    provider: IntegrationProvider
    resource_id: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=200)
    fingerprint: str = Field(min_length=64, max_length=64)
    status: MutationStatus
    confirmed_by: str | None = Field(default=None, max_length=200)
    provider_resource_id: str | None = Field(default=None, max_length=500)
    error_code: str | None = Field(default=None, max_length=100)
    occurred_at: datetime


class CalendarMutationCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: IntegrationProvider
    workflow_id: str | None = Field(default=None, max_length=100)
    event: CalendarEventSnapshot
    prior_event: CalendarEventSnapshot | None = None


class CalendarMutationPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=100)
    provider: IntegrationProvider
    workflow_id: str | None = None
    event: CalendarEventSnapshot
    prior_event: CalendarEventSnapshot | None = None
    kind: MutationKind
    fingerprint: str = Field(min_length=64, max_length=64)
    created_at: datetime


class FollowUpCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    due_at: datetime
    channel: IntegrationProvider


class FollowUp(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=100)
    workflow_id: str
    reason: str
    due_at: datetime
    channel: IntegrationProvider
    status: FollowUpStatus
    dedupe_key: str = Field(min_length=64, max_length=64)
    created_at: datetime
    updated_at: datetime


class DailyCommunicationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    analyzed_messages: int
    review_required: int
    scheduled_follow_ups: int
    due_follow_ups: int
    planned_mutations: int
    confirmed_mutations: int


class CommunicationExport(BaseModel):
    model_config = ConfigDict(frozen=True)

    exported_at: datetime
    records: list[CommunicationRecord]
    drafts: list[OutboundDraft]
    follow_ups: list[FollowUp]
    mutation_audits: list[MutationAudit]


class ApplicationCommunicationStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str
    stage: ApplicationCommunicationStage
    source_record_id: str
    category: MessageCategory
    updated_at: datetime
