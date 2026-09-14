from __future__ import annotations

import json
import unicodedata
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr

from job_apply_pro.domain.communications import (
    CalendarCreateFields,
    CalendarEventSnapshot,
    IntegrationProvider,
    NormalizedMessage,
    OutboundDraft,
    ProviderSyncMode,
)
from job_apply_pro.domain.mail import (
    ProviderMailResult,
    VerifiedMailAttachment,
    validate_mail_bundle,
)
from job_apply_pro.domain.mail_threading import (
    parse_gmail_reply_headers,
    parse_outlook_reply_headers,
    validate_mailbox,
)


class ProviderMessageBatch:
    """Internal provider result whose opaque cursor must not cross the API boundary."""

    def __init__(
        self,
        *,
        messages: list[NormalizedMessage],
        cursor: SecretStr,
        mode: ProviderSyncMode,
    ) -> None:
        self.messages = messages
        self.cursor = cursor
        self.mode = mode


def normalize_gmail_message(payload: dict[str, object]) -> NormalizedMessage:
    recipients = payload.get("to", [])
    attachments = payload.get("attachments", [])
    identifiers = payload.get("identifiers", [])
    urls = payload.get("urls", [])
    return NormalizedMessage(
        provider=IntegrationProvider.GMAIL,
        provider_message_id=str(payload["id"]),
        provider_thread_id=str(payload["threadId"]),
        sender=str(payload["from"])[:500],
        recipients=[str(value) for value in recipients] if isinstance(recipients, list) else [],
        subject=str(payload.get("subject", ""))[:1_000],
        body_text=str(payload.get("text", "")),
        received_at=datetime.fromisoformat(str(payload["receivedAt"])),
        attachment_names=(
            [str(value) for value in attachments] if isinstance(attachments, list) else []
        ),
        referenced_identifiers=(
            [str(value) for value in identifiers] if isinstance(identifiers, list) else []
        ),
        referenced_urls=[str(value) for value in urls] if isinstance(urls, list) else [],
        reply_headers=parse_gmail_reply_headers(payload.get("headers")),
    )


def normalize_outlook_message(payload: dict[str, object]) -> NormalizedMessage:
    sender = payload.get("sender", {})
    if not isinstance(sender, dict):
        sender = {}
    sender_address = sender.get("emailAddress", sender)
    if not isinstance(sender_address, dict):
        sender_address = {}
    recipients = payload.get("toRecipients", [])
    attachments = payload.get("attachments", [])
    identifiers = payload.get("identifiers", [])
    urls = payload.get("urls", [])
    recipient_items = recipients if isinstance(recipients, list) else []
    attachment_items = attachments if isinstance(attachments, list) else []
    return NormalizedMessage(
        provider=IntegrationProvider.OUTLOOK,
        provider_message_id=str(payload["id"]),
        provider_thread_id=str(payload["conversationId"]),
        sender=str(sender_address.get("address", "unknown@example.invalid"))[:500],
        recipients=[
            str(item.get("address", "")) for item in recipient_items if isinstance(item, dict)
        ],
        subject=str(payload.get("subject", ""))[:1_000],
        body_text=str(payload.get("bodyPreview", "")),
        received_at=datetime.fromisoformat(str(payload["receivedDateTime"])),
        attachment_names=[
            str(item.get("name", "")) for item in attachment_items if isinstance(item, dict)
        ],
        referenced_identifiers=(
            [str(value) for value in identifiers] if isinstance(identifiers, list) else []
        ),
        referenced_urls=[str(value) for value in urls] if isinstance(urls, list) else [],
        reply_headers=parse_outlook_reply_headers(payload),
    )


class ProviderNotConfiguredError(RuntimeError):
    pass


class ProviderMutationError(RuntimeError):
    pass


class UnsupportedMailAttachmentsError(ProviderMutationError):
    def __init__(self) -> None:
        super().__init__("Sending document attachments is not supported; no message was sent")


class ProviderSendUncertainError(ProviderMutationError):
    def __init__(self) -> None:
        super().__init__(
            "Mail send outcome is uncertain; inspect the provider before sending again"
        )


class ProviderCalendarUncertainError(ProviderMutationError):
    def __init__(self) -> None:
        super().__init__(
            "Calendar creation outcome is uncertain; inspect the provider before creating again"
        )


class ProviderCalendarNotAppliedError(ProviderMutationError):
    """A typed pre-dispatch refusal or clean rejection proving no create occurred."""

    def __init__(
        self, message: str = "The calendar provider did not apply the create request"
    ) -> None:
        super().__init__(message)


MAX_CALENDAR_CREATE_WIRE_BYTES = 65_536


def validate_calendar_create(event: CalendarCreateFields) -> CalendarCreateFields:
    """Pure, no-repair validation before a calendar attempt is claimed or dispatched."""
    try:
        if (
            not isinstance(event, CalendarCreateFields)
            or event.model_extra
            or set(event.__dict__) - set(CalendarCreateFields.model_fields)
        ):
            raise ValueError
        reviewed = CalendarCreateFields.model_validate(event.model_dump(mode="python"))
        if reviewed.conferencing_url is not None:
            raise ValueError
        if not reviewed.title.strip() or (
            reviewed.location is not None and not reviewed.location.strip()
        ):
            raise ValueError
        for value in (reviewed.title, reviewed.location):
            if value is not None and (
                any(unicodedata.category(character).startswith("C") for character in value)
                or any(character in "\u2028\u2029" for character in value)
            ):
                raise ValueError
        zone = ZoneInfo(reviewed.time_zone)
        for timestamp in (reviewed.start_at, reviewed.end_at):
            in_zone = timestamp.astimezone(zone)
            if timestamp.utcoffset() != in_zone.utcoffset() or timestamp.replace(
                tzinfo=None
            ) != in_zone.replace(tzinfo=None):
                raise ValueError
        normalized_attendees = [
            validate_mailbox(attendee).casefold() for attendee in reviewed.attendees
        ]
        if len(normalized_attendees) != len(set(normalized_attendees)):
            raise ValueError
        # Invitations have provider-specific side effects. This API-only alpha
        # supports an explicit no-invitations policy, so recipients fail closed.
        if (
            reviewed.attendee_notification_policy != "NONE"
            or reviewed.reminder_policy != "NONE"
            or reviewed.visibility_policy != "PRIVATE"
            or reviewed.availability_policy != "BUSY"
            or reviewed.attendees
        ):
            raise ValueError
        # Bound the neutral snapshot plus a conservative per-attendee/field envelope
        # budget for either supported provider's JSON representation.
        size = len(
            json.dumps(
                reviewed.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        if size + 96 * len(reviewed.attendees) + 2_048 > MAX_CALENDAR_CREATE_WIRE_BYTES:
            raise ValueError
        return reviewed
    except (ValueError, TypeError, AttributeError, ZoneInfoNotFoundError) as error:
        raise ValueError("Calendar creation payload is invalid or unsupported") from error


def reject_mail_attachments(document_version_ids: Sequence[str]) -> None:
    """Do not silently send text when reviewed document selections cannot be delivered."""
    if document_version_ids:
        raise UnsupportedMailAttachmentsError()


class CredentialBroker(Protocol):
    """Resolves an opaque OS-keychain reference without exposing it to the renderer."""

    def resolve(self, credential_reference: str) -> str: ...


class MessageProviderAdapter(Protocol):
    provider: IntegrationProvider

    def list_messages(self, *, since: datetime | None = None) -> list[NormalizedMessage]: ...

    def sync_messages(
        self, *, cursor: SecretStr | None, since: datetime | None = None
    ) -> ProviderMessageBatch: ...

    def send(
        self,
        draft: OutboundDraft,
        *,
        idempotency_key: str,
        attachments: tuple[VerifiedMailAttachment, ...] = (),
    ) -> ProviderMailResult: ...


class CalendarProviderAdapter(Protocol):
    provider: IntegrationProvider

    def list_events(
        self, *, start_at: datetime, end_at: datetime
    ) -> list[CalendarEventSnapshot]: ...

    def create_event(self, event: CalendarCreateFields, *, idempotency_key: str) -> str: ...

    def update_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str: ...


class DisabledMessageProvider:
    def __init__(self, provider: IntegrationProvider) -> None:
        self.provider = provider

    def list_messages(self, *, since: datetime | None = None) -> list[NormalizedMessage]:
        del since
        raise ProviderNotConfiguredError(f"{self.provider.value} read access is not configured")

    def sync_messages(
        self, *, cursor: SecretStr | None, since: datetime | None = None
    ) -> ProviderMessageBatch:
        del cursor, since
        raise ProviderNotConfiguredError(f"{self.provider.value} read access is not configured")

    def send(
        self,
        draft: OutboundDraft,
        *,
        idempotency_key: str,
        attachments: tuple[VerifiedMailAttachment, ...] = (),
    ) -> ProviderMailResult:
        if not attachments:
            reject_mail_attachments(draft.document_version_ids)
        validate_mail_bundle(draft, attachments)
        del draft, idempotency_key
        raise ProviderNotConfiguredError(f"{self.provider.value} write access is not configured")


class DisabledCalendarProvider:
    def __init__(self, provider: IntegrationProvider) -> None:
        self.provider = provider

    def list_events(self, *, start_at: datetime, end_at: datetime) -> list[CalendarEventSnapshot]:
        del start_at, end_at
        raise ProviderNotConfiguredError(f"{self.provider.value} read access is not configured")

    def create_event(self, event: CalendarCreateFields, *, idempotency_key: str) -> str:
        del event, idempotency_key
        raise ProviderCalendarNotAppliedError(
            f"{self.provider.value} write access is not configured"
        )

    def update_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str:
        del event, idempotency_key
        raise ProviderNotConfiguredError(f"{self.provider.value} write access is not configured")


class FixtureMessageProvider:
    """Sanitized replay adapter for deterministic provider-contract validation."""

    def __init__(
        self, provider: IntegrationProvider, messages: list[NormalizedMessage] | None = None
    ) -> None:
        self.provider = provider
        self._messages = messages or []
        self.sent: list[tuple[str, str]] = []
        self.sync_count = 0

    def list_messages(self, *, since: datetime | None = None) -> list[NormalizedMessage]:
        return [
            message for message in self._messages if since is None or message.received_at >= since
        ]

    def sync_messages(
        self, *, cursor: SecretStr | None, since: datetime | None = None
    ) -> ProviderMessageBatch:
        self.sync_count += 1
        return ProviderMessageBatch(
            messages=self.list_messages(since=since),
            cursor=SecretStr(f"fixture-cursor-{self.sync_count}"),
            mode=(ProviderSyncMode.INITIAL if cursor is None else ProviderSyncMode.INCREMENTAL),
        )

    def send(
        self,
        draft: OutboundDraft,
        *,
        idempotency_key: str,
        attachments: tuple[VerifiedMailAttachment, ...] = (),
    ) -> ProviderMailResult:
        if not attachments:
            reject_mail_attachments(draft.document_version_ids)
        validate_mail_bundle(draft, attachments)
        self.sent.append((draft.id, idempotency_key))
        return ProviderMailResult(f"fixture-message-{len(self.sent)}")


class FixtureCalendarProvider:
    """Sanitized create-only replay adapter without network access."""

    def __init__(
        self, provider: IntegrationProvider, events: list[CalendarEventSnapshot] | None = None
    ) -> None:
        self.provider = provider
        self.events = events or []
        self.mutations: list[tuple[str, str]] = []

    def list_events(self, *, start_at: datetime, end_at: datetime) -> list[CalendarEventSnapshot]:
        return [
            event for event in self.events if event.start_at < end_at and event.end_at > start_at
        ]

    def create_event(self, event: CalendarCreateFields, *, idempotency_key: str) -> str:
        reviewed = validate_calendar_create(event)
        self.mutations.append(("create", idempotency_key))
        provider_id = f"fixture-event-{len(self.mutations)}"
        self.events.append(
            CalendarEventSnapshot(
                provider_event_id=provider_id,
                **reviewed.model_dump(
                    exclude={
                        "attendee_notification_policy",
                        "reminder_policy",
                        "visibility_policy",
                        "availability_policy",
                    }
                ),
            )
        )
        return provider_id

    def update_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str:
        del event, idempotency_key
        raise ProviderMutationError("Calendar updates are not supported; no update was requested")
