from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta, tzinfo
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from job_apply_pro.domain.communications import (
    ApplicationCommunicationStage,
    ApplicationCommunicationStatus,
    ApplicationCorrelation,
    AttachmentCandidate,
    AttachmentVerification,
    CalendarEventSnapshot,
    CalendarMutationCreate,
    CalendarMutationPlan,
    CommunicationAnalysis,
    CommunicationExport,
    CommunicationRecord,
    DailyCommunicationSummary,
    DraftCreate,
    FollowUp,
    FollowUpCreate,
    FollowUpStatus,
    IntegrationHealth,
    IntegrationProvider,
    IntegrationStatus,
    MessageCategory,
    MessageClassification,
    MutationAudit,
    MutationConfirmation,
    MutationKind,
    MutationStatus,
    NormalizedMessage,
    OutboundDraft,
    OutboundPolicy,
    ProviderCalendarSyncResult,
    ProviderMessageSyncResult,
    ReplyDraft,
    SchedulingRecommendation,
    SchedulingRequest,
    SyncedCalendarEvent,
)
from job_apply_pro.domain.workbench import WorkflowRunSnapshot
from job_apply_pro.integrations.communications import (
    CalendarProviderAdapter,
    DisabledCalendarProvider,
    DisabledMessageProvider,
    MessageProviderAdapter,
    ProviderMutationError,
    ProviderNotConfiguredError,
)
from job_apply_pro.integrations.configuration import ProviderConnectionConfig
from job_apply_pro.storage.repository_contracts import (
    CandidateKnowledgeRepositoryProtocol,
    CommunicationRepositoryProtocol,
)

_CATEGORY_SIGNALS = {
    MessageCategory.OFFER: ("offer", "compensation", "start date"),
    MessageCategory.REJECTION: ("not moving forward", "other candidates", "regret"),
    MessageCategory.INTERVIEW_REQUEST: ("interview", "availability", "schedule"),
    MessageCategory.ASSESSMENT_INVITATION: ("assessment", "coding test", "take-home"),
    MessageCategory.SCREENING_REQUEST: ("screening", "questionnaire", "phone screen"),
    MessageCategory.APPLICATION_CONFIRMATION: ("application received", "application submitted"),
    MessageCategory.STATUS_UPDATE: ("application status", "under review", "next step"),
    MessageCategory.RECRUITER_INQUIRY: ("recruiter", "opportunity", "your background"),
    MessageCategory.JOB_ALERT: ("job alert", "new jobs", "recommended jobs"),
    MessageCategory.NEWSLETTER: ("newsletter", "unsubscribe"),
}
_ISO_TIME_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})\b")
_TRACKING_STAGES = {
    MessageCategory.APPLICATION_CONFIRMATION: ApplicationCommunicationStage.SUBMITTED,
    MessageCategory.RECRUITER_INQUIRY: ApplicationCommunicationStage.RECRUITER_CONTACT,
    MessageCategory.SCREENING_REQUEST: ApplicationCommunicationStage.SCREENING,
    MessageCategory.INTERVIEW_REQUEST: ApplicationCommunicationStage.INTERVIEW,
    MessageCategory.ASSESSMENT_INVITATION: ApplicationCommunicationStage.ASSESSMENT,
    MessageCategory.REJECTION: ApplicationCommunicationStage.REJECTED,
    MessageCategory.OFFER: ApplicationCommunicationStage.OFFER,
}


class CommunicationService:
    CALENDAR_LOOKBACK = timedelta(days=1)
    CALENDAR_LOOKAHEAD = timedelta(days=60)

    def __init__(
        self,
        repository: CommunicationRepositoryProtocol | None = None,
        *,
        message_adapters: dict[IntegrationProvider, MessageProviderAdapter] | None = None,
        calendar_adapters: dict[IntegrationProvider, CalendarProviderAdapter] | None = None,
        automatic_categories: set[MessageCategory] | None = None,
        provider_configs: dict[IntegrationProvider, ProviderConnectionConfig] | None = None,
        knowledge_repository: CandidateKnowledgeRepositoryProtocol | None = None,
    ) -> None:
        self._repository = repository
        self._message_adapters: dict[IntegrationProvider, MessageProviderAdapter] = {
            IntegrationProvider.GMAIL: DisabledMessageProvider(IntegrationProvider.GMAIL),
            IntegrationProvider.OUTLOOK: DisabledMessageProvider(IntegrationProvider.OUTLOOK),
        }
        self._message_adapters.update(message_adapters or {})
        self._calendar_adapters: dict[IntegrationProvider, CalendarProviderAdapter] = {
            IntegrationProvider.GOOGLE_CALENDAR: DisabledCalendarProvider(
                IntegrationProvider.GOOGLE_CALENDAR
            ),
            IntegrationProvider.OUTLOOK_CALENDAR: DisabledCalendarProvider(
                IntegrationProvider.OUTLOOK_CALENDAR
            ),
        }
        self._calendar_adapters.update(calendar_adapters or {})
        self._automatic_categories = automatic_categories or set()
        self._provider_configs = provider_configs or {}
        self._knowledge_repository = knowledge_repository

    def health(self) -> list[IntegrationHealth]:
        health: list[IntegrationHealth] = []
        for provider in IntegrationProvider:
            config = self._provider_configs.get(provider)
            if config is None:
                health.append(
                    IntegrationHealth(
                        provider=provider,
                        status=IntegrationStatus.NOT_CONFIGURED,
                        message="OAuth client and user authorization are not configured",
                    )
                )
                continue
            adapter = (
                self._message_adapters.get(provider)
                if provider in {IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK}
                else self._calendar_adapters.get(provider)
            )
            connected = adapter is not None and not isinstance(
                adapter, (DisabledMessageProvider, DisabledCalendarProvider)
            )
            health.append(
                IntegrationHealth(
                    provider=provider,
                    status=(
                        IntegrationStatus.CONNECTED
                        if connected
                        else IntegrationStatus.AUTHORIZATION_REQUIRED
                    ),
                    message=(
                        "Provider adapter is connected"
                        if connected
                        else "Credential reference exists; provider authorization is required"
                    ),
                    read_enabled=config.read_enabled and connected,
                    write_enabled=config.write_enabled and connected,
                    credential_reference=config.credential_reference,
                    granted_scopes=config.granted_scopes,
                    account_hint=config.account_hint,
                )
            )
        return health

    def classify(self, message: NormalizedMessage) -> MessageClassification:
        haystack = f"{message.subject} {message.body_text}".casefold()
        best_category = MessageCategory.SPAM_OR_UNRELATED
        best_signals: list[str] = []
        for category, signals in _CATEGORY_SIGNALS.items():
            matched = [signal for signal in signals if signal in haystack]
            if len(matched) > len(best_signals):
                best_category, best_signals = category, matched
        confidence = min(1.0, 0.5 + 0.2 * len(best_signals)) if best_signals else 0.2
        return MessageClassification(
            category=best_category,
            confidence=confidence,
            matched_signals=best_signals,
            requires_review=confidence < 0.7,
        )

    def correlate(
        self, message: NormalizedMessage, workflows: list[WorkflowRunSnapshot]
    ) -> ApplicationCorrelation:
        haystack = f"{message.sender} {message.subject} {message.body_text}".casefold()
        if self._repository is not None:
            prior_thread = next(
                (
                    record
                    for record in self._repository.list_records()
                    if record.analysis.message.provider is message.provider
                    and record.analysis.message.provider_thread_id == message.provider_thread_id
                    and record.analysis.correlation.workflow_id is not None
                ),
                None,
            )
            if prior_thread is not None:
                return ApplicationCorrelation(
                    workflow_id=prior_thread.analysis.correlation.workflow_id,
                    confidence=0.95,
                    matched_signals=["provider_thread_id"],
                    requires_review=False,
                )
        scored: list[tuple[float, WorkflowRunSnapshot, list[str]]] = []
        for workflow in workflows:
            signals: list[str] = []
            score = 0.0
            if workflow.workflow_id in message.referenced_identifiers or (
                workflow.workflow_id.casefold() in haystack
            ):
                signals.append("workflow_id")
                score += 0.6
            if workflow.application_id in message.referenced_identifiers or (
                workflow.application_id.casefold() in haystack
            ):
                signals.append("application_id")
                score += 0.6
            if workflow.employer.casefold() in haystack:
                signals.append("employer")
                score += 0.5
            if workflow.title.casefold() in haystack:
                signals.append("title")
                score += 0.5
            score = min(1.0, score)
            scored.append((score, workflow, signals))
        if not scored:
            return ApplicationCorrelation(confidence=0, matched_signals=[], requires_review=True)
        score, workflow, signals = max(scored, key=lambda item: item[0])
        return ApplicationCorrelation(
            workflow_id=workflow.workflow_id if score else None,
            confidence=score,
            matched_signals=signals,
            requires_review=score < 1,
        )

    def draft_reply(
        self, message: NormalizedMessage, classification: MessageClassification
    ) -> ReplyDraft:
        if classification.category is MessageCategory.INTERVIEW_REQUEST:
            body = (
                "Thank you for the interview invitation. I remain interested. "
                "Please confirm the available time options and time zone."
            )
        elif classification.category is MessageCategory.RECRUITER_INQUIRY:
            body = (
                "Thank you for reaching out. I am interested in learning more "
                "about the role, team, location, and hiring process."
            )
        else:
            body = (
                "Thank you for the update. I have received your message and "
                "will review the details."
            )
        return ReplyDraft(
            subject=f"Re: {message.subject}",
            body_text=body,
            category=classification.category,
            evidence=[message.provider_message_id],
        )

    def extract_proposed_times(self, message: NormalizedMessage) -> list[datetime]:
        values: list[datetime] = []
        for match in _ISO_TIME_PATTERN.findall(f"{message.subject} {message.body_text}"):
            normalized = match.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is not None and parsed not in values:
                values.append(parsed)
        return values[:50]

    def rank_times(
        self, request: SchedulingRequest, events: list[CalendarEventSnapshot]
    ) -> list[SchedulingRecommendation]:
        requested_zone: tzinfo
        if request.time_zone.upper() in {"UTC", "ETC/UTC"}:
            requested_zone = UTC
        else:
            try:
                requested_zone = ZoneInfo(request.time_zone)
            except ZoneInfoNotFoundError as error:
                raise ValueError(f"Unknown IANA time zone: {request.time_zone}") from error
        recommendations: list[SchedulingRecommendation] = []
        for start in sorted(request.proposed_starts):
            end = start + timedelta(minutes=request.duration_minutes)
            conflicts = [
                event.provider_event_id
                for event in events
                if start < event.end_at and end > event.start_at
            ]
            local_start = start.astimezone(requested_zone)
            local_end = end.astimezone(requested_zone)
            start_minutes = local_start.hour * 60 + local_start.minute
            end_minutes = local_end.hour * 60 + local_end.minute
            outside_hours = not (
                local_start.date() == local_end.date()
                and request.working_hour_start * 60 <= start_minutes
                and end_minutes <= request.working_hour_end * 60
            )
            if outside_hours:
                conflicts.append("OUTSIDE_WORKING_HOURS")
            recommendations.append(
                SchedulingRecommendation(
                    start_at=start,
                    end_at=end,
                    time_zone=request.time_zone,
                    conflicts=conflicts,
                    rank=1,
                    available=not conflicts,
                )
            )
        ordered = sorted(recommendations, key=lambda item: (not item.available, item.start_at))
        return [item.model_copy(update={"rank": index}) for index, item in enumerate(ordered, 1)]

    def verify_attachment(
        self, candidate: AttachmentCandidate, *, expected_profile_id: str
    ) -> AttachmentVerification:
        reasons: list[str] = []
        if self._knowledge_repository is not None:
            version = self._knowledge_repository.get_version_record(candidate.document_version_id)
            if version is None:
                reasons.append("DOCUMENT_VERSION_NOT_FOUND")
            else:
                document = self._knowledge_repository.get_document(version.document_id)
                if document is None:
                    reasons.append("DOCUMENT_NOT_FOUND")
                elif document.profile_id != expected_profile_id:
                    reasons.append("DOCUMENT_PROFILE_MISMATCH")
                if candidate.file_name != version.file_name:
                    reasons.append("FILE_NAME_MISMATCH")
                if candidate.media_type != version.media_type:
                    reasons.append("MEDIA_TYPE_MISMATCH")
        if candidate.profile_id != expected_profile_id:
            reasons.append("PROFILE_MISMATCH")
        if candidate.media_type not in {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }:
            reasons.append("UNSUPPORTED_MEDIA_TYPE")
        if candidate.size_bytes > 10 * 1024 * 1024:
            reasons.append("FILE_TOO_LARGE")
        if not candidate.file_name.casefold().endswith((".pdf", ".docx")):
            reasons.append("UNEXPECTED_FILE_EXTENSION")
        return AttachmentVerification(
            document_version_id=candidate.document_version_id,
            approved=not reasons,
            reasons=reasons,
        )

    def analyze_and_save(
        self, message: NormalizedMessage, workflows: list[WorkflowRunSnapshot]
    ) -> CommunicationRecord:
        repository = self._require_repository()
        classification = self.classify(message)
        analysis = CommunicationAnalysis(
            message=message,
            classification=classification,
            correlation=self.correlate(message, workflows),
            reply_draft=self.draft_reply(message, classification),
            proposed_times=self.extract_proposed_times(message),
            time_proposal_requires_review=True,
        )
        now = datetime.now(UTC)
        return repository.save_record(
            CommunicationRecord(
                id=str(uuid4()),
                analysis=analysis,
                received_at=message.received_at,
                created_at=now,
            )
        )

    def sync_provider_messages(
        self,
        provider: IntegrationProvider,
        *,
        since: datetime | None,
        workflows: list[WorkflowRunSnapshot],
    ) -> ProviderMessageSyncResult:
        if provider not in {IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK}:
            raise ValueError("Message synchronization requires a mail provider")
        if since is not None and (since.tzinfo is None or since.utcoffset() is None):
            raise ValueError("Message synchronization time must include a UTC offset")
        repository = self._require_repository()
        existing_ids = {
            record.analysis.message.provider_message_id
            for record in repository.list_records()
            if record.analysis.message.provider is provider
        }
        binding_fingerprint = self._provider_binding_fingerprint(provider)
        prior_state = repository.get_sync_state(provider, binding_fingerprint)
        batch = self._message_adapters[provider].sync_messages(
            cursor=prior_state.cursor if prior_state is not None else None,
            since=since,
        )
        messages = batch.messages
        record_ids: list[str] = []
        imported_count = 0
        for message in messages:
            if message.provider is not provider:
                raise ProviderMutationError(
                    "Provider returned a message for the wrong account type"
                )
            is_new = message.provider_message_id not in existing_ids
            record = self.analyze_and_save(message, workflows)
            record_ids.append(record.id)
            if is_new:
                existing_ids.add(message.provider_message_id)
                imported_count += 1
        saved_state = repository.save_sync_state(
            provider,
            batch.cursor,
            binding_fingerprint,
            prior_state.cursor if prior_state is not None else None,
        )
        return ProviderMessageSyncResult(
            provider=provider,
            fetched_count=len(messages),
            imported_count=imported_count,
            duplicate_count=len(messages) - imported_count,
            record_ids=record_ids,
            sync_mode=batch.mode,
            cursor_updated_at=saved_state.updated_at,
        )

    def list_records(self) -> list[CommunicationRecord]:
        return self._require_repository().list_records()

    def sync_provider_calendar(
        self,
        provider: IntegrationProvider,
        *,
        now: datetime | None = None,
    ) -> ProviderCalendarSyncResult:
        if provider not in {
            IntegrationProvider.GOOGLE_CALENDAR,
            IntegrationProvider.OUTLOOK_CALENDAR,
        }:
            raise ValueError("Calendar synchronization requires a calendar provider")
        anchor = now or datetime.now(UTC)
        if anchor.tzinfo is None or anchor.utcoffset() is None:
            raise ValueError("Calendar synchronization time must include a UTC offset")
        window_start = anchor - self.CALENDAR_LOOKBACK
        window_end = anchor + self.CALENDAR_LOOKAHEAD
        events = self._calendar_adapters[provider].list_events(
            start_at=window_start,
            end_at=window_end,
        )
        event_ids = [event.provider_event_id for event in events]
        if len(event_ids) != len(set(event_ids)):
            raise ProviderMutationError("Provider returned duplicate calendar event identifiers")
        stored, removed_count = self._require_repository().reconcile_calendar_events(
            provider,
            self._provider_binding_fingerprint(provider),
            events,
            window_start=window_start,
            window_end=window_end,
        )
        synced_at = max((item.synced_at for item in stored), default=datetime.now(UTC))
        return ProviderCalendarSyncResult(
            provider=provider,
            fetched_count=len(events),
            stored_count=len(stored),
            removed_count=removed_count,
            window_start=window_start,
            window_end=window_end,
            synced_at=synced_at,
        )

    def list_synced_calendar_events(
        self, *, now: datetime | None = None
    ) -> list[SyncedCalendarEvent]:
        anchor = now or datetime.now(UTC)
        if anchor.tzinfo is None or anchor.utcoffset() is None:
            raise ValueError("Calendar event listing time must include a UTC offset")
        return self._require_repository().list_calendar_events(
            {
                provider: self._provider_binding_fingerprint(provider)
                for provider in (
                    IntegrationProvider.GOOGLE_CALENDAR,
                    IntegrationProvider.OUTLOOK_CALENDAR,
                )
            },
            start_at=anchor,
            end_at=anchor + self.CALENDAR_LOOKAHEAD,
        )

    def _provider_binding_fingerprint(self, provider: IntegrationProvider) -> str:
        config = self._provider_configs.get(provider)
        binding_value = "\0".join(
            (
                provider.value,
                (config.credential_reference or "configured") if config is not None else "fixture",
                config.account_hint or "" if config is not None else "",
            )
        )
        return hashlib.sha256(binding_value.encode()).hexdigest()

    def search_records(
        self,
        *,
        query: str | None = None,
        category: MessageCategory | None = None,
        workflow_id: str | None = None,
    ) -> list[CommunicationRecord]:
        records = self.list_records()
        if category is not None:
            records = [
                record for record in records if record.analysis.classification.category is category
            ]
        if workflow_id is not None:
            records = [
                record
                for record in records
                if record.analysis.correlation.workflow_id == workflow_id
            ]
        if query:
            needle = query.casefold()
            records = [
                record
                for record in records
                if needle
                in " ".join(
                    (
                        record.analysis.message.sender,
                        record.analysis.message.subject,
                        record.analysis.message.body_text,
                    )
                ).casefold()
            ]
        return records

    def create_draft(self, command: DraftCreate) -> OutboundDraft:
        repository = self._require_repository()
        if repository.get_record(command.analysis_id) is None:
            raise LookupError(f"Communication analysis {command.analysis_id} was not found")
        if self._knowledge_repository is not None:
            missing_versions = [
                version_id
                for version_id in command.document_version_ids
                if self._knowledge_repository.get_version_record(version_id) is None
            ]
            if missing_versions:
                raise LookupError(
                    f"Attachment document versions were not found: {', '.join(missing_versions)}"
                )
        policy = command.policy
        if (
            policy is OutboundPolicy.AUTOMATIC
            and command.category not in self._automatic_categories
        ):
            raise ValueError(f"Automatic sending is not enabled for {command.category.value}")
        now = datetime.now(UTC)
        draft_id = str(uuid4())
        fingerprint = self._fingerprint(
            {
                "id": draft_id,
                "analysis_id": command.analysis_id,
                "provider": command.provider.value,
                "thread": command.provider_thread_id,
                "recipient": command.recipient,
                "subject": command.subject,
                "body": command.body_text,
                "documents": command.document_version_ids,
            }
        )
        return repository.save_draft(
            OutboundDraft(
                id=draft_id,
                **command.model_dump(),
                fingerprint=fingerprint,
                created_at=now,
                updated_at=now,
            )
        )

    def list_drafts(self) -> list[OutboundDraft]:
        return self._require_repository().list_drafts()

    def send_draft(self, draft_id: str, command: MutationConfirmation) -> MutationAudit:
        repository = self._require_repository()
        replay = repository.find_audit_by_idempotency(command.idempotency_key)
        if replay is not None:
            return replay
        draft = repository.get_draft(draft_id)
        if draft is None:
            raise LookupError(f"Outbound draft {draft_id} was not found")
        if command.fingerprint != draft.fingerprint:
            raise ValueError("Draft changed after review; refresh and confirm the new fingerprint")
        if draft.provider not in {IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK}:
            raise ValueError("Draft provider must be Gmail or Outlook")
        audit = self._new_audit(
            kind=MutationKind.SEND_MESSAGE,
            provider=draft.provider,
            resource_id=draft.id,
            command=command,
        )
        repository.add_audit(audit)
        try:
            provider_id = self._message_adapters[draft.provider].send(
                draft, idempotency_key=command.idempotency_key
            )
        except (ProviderNotConfiguredError, ProviderMutationError) as error:
            failed = audit.model_copy(
                update={
                    "status": MutationStatus.FAILED,
                    "error_code": type(error).__name__,
                    "occurred_at": datetime.now(UTC),
                }
            )
            repository.add_audit(failed)
            raise
        confirmed = audit.model_copy(
            update={
                "status": MutationStatus.CONFIRMED,
                "provider_resource_id": provider_id,
                "occurred_at": datetime.now(UTC),
            }
        )
        return repository.add_audit(confirmed)

    def plan_calendar_mutation(self, command: CalendarMutationCreate) -> CalendarMutationPlan:
        repository = self._require_repository()
        if command.provider not in {
            IntegrationProvider.GOOGLE_CALENDAR,
            IntegrationProvider.OUTLOOK_CALENDAR,
        }:
            raise ValueError("Calendar plans require a calendar provider")
        kind = (
            MutationKind.UPDATE_CALENDAR_EVENT
            if command.prior_event is not None
            else MutationKind.CREATE_CALENDAR_EVENT
        )
        plan_id = str(uuid4())
        fingerprint = self._fingerprint(
            {
                "id": plan_id,
                "provider": command.provider.value,
                "workflow_id": command.workflow_id,
                "event": command.event.model_dump(mode="json"),
                "prior_event": (
                    command.prior_event.model_dump(mode="json")
                    if command.prior_event is not None
                    else None
                ),
            }
        )
        return repository.save_calendar_plan(
            CalendarMutationPlan(
                id=plan_id,
                **command.model_dump(),
                kind=kind,
                fingerprint=fingerprint,
                created_at=datetime.now(UTC),
            )
        )

    def execute_calendar_mutation(
        self, plan_id: str, command: MutationConfirmation
    ) -> MutationAudit:
        repository = self._require_repository()
        replay = repository.find_audit_by_idempotency(command.idempotency_key)
        if replay is not None:
            return replay
        plan = repository.get_calendar_plan(plan_id)
        if plan is None:
            raise LookupError(f"Calendar plan {plan_id} was not found")
        if command.fingerprint != plan.fingerprint:
            raise ValueError("Calendar plan changed after review; refresh and confirm again")
        audit = self._new_audit(
            kind=plan.kind,
            provider=plan.provider,
            resource_id=plan.id,
            command=command,
        )
        repository.add_audit(audit)
        adapter = self._calendar_adapters[plan.provider]
        try:
            provider_id = (
                adapter.create_event(plan.event, idempotency_key=command.idempotency_key)
                if plan.kind is MutationKind.CREATE_CALENDAR_EVENT
                else adapter.update_event(plan.event, idempotency_key=command.idempotency_key)
            )
        except (ProviderNotConfiguredError, ProviderMutationError) as error:
            failed = audit.model_copy(
                update={
                    "status": MutationStatus.FAILED,
                    "error_code": type(error).__name__,
                    "occurred_at": datetime.now(UTC),
                }
            )
            repository.add_audit(failed)
            raise
        return repository.add_audit(
            audit.model_copy(
                update={
                    "status": MutationStatus.CONFIRMED,
                    "provider_resource_id": provider_id,
                    "occurred_at": datetime.now(UTC),
                }
            )
        )

    def schedule_follow_up(self, command: FollowUpCreate) -> FollowUp:
        now = datetime.now(UTC)
        dedupe_key = self._fingerprint(
            {
                "workflow_id": command.workflow_id,
                "reason": command.reason,
                "due_at": command.due_at.isoformat(),
                "channel": command.channel.value,
            }
        )
        return self._require_repository().save_follow_up(
            FollowUp(
                id=str(uuid4()),
                **command.model_dump(),
                status=FollowUpStatus.SCHEDULED,
                dedupe_key=dedupe_key,
                created_at=now,
                updated_at=now,
            )
        )

    def list_follow_ups(self) -> list[FollowUp]:
        now = datetime.now(UTC)
        return [
            item.model_copy(
                update={"status": FollowUpStatus.DUE}
                if item.status is FollowUpStatus.SCHEDULED and item.due_at <= now
                else {}
            )
            for item in self._require_repository().list_follow_ups()
        ]

    def list_audits(self) -> list[MutationAudit]:
        return self._require_repository().list_audits()

    def daily_summary(self) -> DailyCommunicationSummary:
        records = self.list_records()
        follow_ups = self.list_follow_ups()
        audits = self.list_audits()
        return DailyCommunicationSummary(
            generated_at=datetime.now(UTC),
            analyzed_messages=len(records),
            review_required=sum(
                record.analysis.classification.requires_review
                or record.analysis.correlation.requires_review
                for record in records
            ),
            scheduled_follow_ups=sum(
                item.status is FollowUpStatus.SCHEDULED for item in follow_ups
            ),
            due_follow_ups=sum(item.status is FollowUpStatus.DUE for item in follow_ups),
            planned_mutations=sum(audit.status is MutationStatus.PLANNED for audit in audits),
            confirmed_mutations=sum(audit.status is MutationStatus.CONFIRMED for audit in audits),
        )

    def export(self) -> CommunicationExport:
        return CommunicationExport(
            exported_at=datetime.now(UTC),
            records=self.list_records(),
            drafts=self.list_drafts(),
            follow_ups=self.list_follow_ups(),
            mutation_audits=self.list_audits(),
        )

    def tracking_statuses(self) -> list[ApplicationCommunicationStatus]:
        statuses: dict[str, ApplicationCommunicationStatus] = {}
        for record in reversed(self.list_records()):
            workflow_id = record.analysis.correlation.workflow_id
            stage = _TRACKING_STAGES.get(record.analysis.classification.category)
            if workflow_id is None or stage is None:
                continue
            statuses[workflow_id] = ApplicationCommunicationStatus(
                workflow_id=workflow_id,
                stage=stage,
                source_record_id=record.id,
                category=record.analysis.classification.category,
                updated_at=record.received_at,
            )
        return sorted(statuses.values(), key=lambda item: item.updated_at, reverse=True)

    def _require_repository(self) -> CommunicationRepositoryProtocol:
        if self._repository is None:
            raise RuntimeError("Communication persistence is not configured")
        return self._repository

    @staticmethod
    def _fingerprint(value: dict[str, object]) -> str:
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _new_audit(
        *,
        kind: MutationKind,
        provider: IntegrationProvider,
        resource_id: str,
        command: MutationConfirmation,
    ) -> MutationAudit:
        return MutationAudit(
            id=str(uuid4()),
            kind=kind,
            provider=provider,
            resource_id=resource_id,
            idempotency_key=command.idempotency_key,
            fingerprint=command.fingerprint,
            status=MutationStatus.PLANNED,
            confirmed_by=command.confirmed_by,
            occurred_at=datetime.now(UTC),
        )
