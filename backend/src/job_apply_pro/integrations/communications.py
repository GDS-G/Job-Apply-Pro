from __future__ import annotations

from datetime import datetime
from typing import Protocol

from job_apply_pro.domain.communications import (
    CalendarEventSnapshot,
    IntegrationProvider,
    NormalizedMessage,
    OutboundDraft,
)


def normalize_gmail_message(payload: dict[str, object]) -> NormalizedMessage:
    recipients = payload.get("to", [])
    attachments = payload.get("attachments", [])
    identifiers = payload.get("identifiers", [])
    urls = payload.get("urls", [])
    return NormalizedMessage(
        provider=IntegrationProvider.GMAIL,
        provider_message_id=str(payload["id"]),
        provider_thread_id=str(payload["threadId"]),
        sender=str(payload["from"]),
        recipients=[str(value) for value in recipients] if isinstance(recipients, list) else [],
        subject=str(payload.get("subject", "")),
        body_text=str(payload.get("text", "")),
        received_at=datetime.fromisoformat(str(payload["receivedAt"])),
        attachment_names=(
            [str(value) for value in attachments] if isinstance(attachments, list) else []
        ),
        referenced_identifiers=(
            [str(value) for value in identifiers] if isinstance(identifiers, list) else []
        ),
        referenced_urls=[str(value) for value in urls] if isinstance(urls, list) else [],
    )


def normalize_outlook_message(payload: dict[str, object]) -> NormalizedMessage:
    sender = payload.get("sender", {})
    if not isinstance(sender, dict):
        sender = {}
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
        sender=str(sender.get("address", "")),
        recipients=[
            str(item.get("address", "")) for item in recipient_items if isinstance(item, dict)
        ],
        subject=str(payload.get("subject", "")),
        body_text=str(payload.get("bodyPreview", "")),
        received_at=datetime.fromisoformat(str(payload["receivedDateTime"])),
        attachment_names=[
            str(item.get("name", "")) for item in attachment_items if isinstance(item, dict)
        ],
        referenced_identifiers=(
            [str(value) for value in identifiers] if isinstance(identifiers, list) else []
        ),
        referenced_urls=[str(value) for value in urls] if isinstance(urls, list) else [],
    )


class ProviderNotConfiguredError(RuntimeError):
    pass


class ProviderMutationError(RuntimeError):
    pass


class CredentialBroker(Protocol):
    """Resolves an opaque OS-keychain reference without exposing it to the renderer."""

    def resolve(self, credential_reference: str) -> str: ...


class MessageProviderAdapter(Protocol):
    provider: IntegrationProvider

    def list_messages(self, *, since: datetime | None = None) -> list[NormalizedMessage]: ...

    def send(self, draft: OutboundDraft, *, idempotency_key: str) -> str: ...


class CalendarProviderAdapter(Protocol):
    provider: IntegrationProvider

    def list_events(
        self, *, start_at: datetime, end_at: datetime
    ) -> list[CalendarEventSnapshot]: ...

    def create_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str: ...

    def update_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str: ...


class DisabledMessageProvider:
    def __init__(self, provider: IntegrationProvider) -> None:
        self.provider = provider

    def list_messages(self, *, since: datetime | None = None) -> list[NormalizedMessage]:
        del since
        raise ProviderNotConfiguredError(f"{self.provider.value} read access is not configured")

    def send(self, draft: OutboundDraft, *, idempotency_key: str) -> str:
        del draft, idempotency_key
        raise ProviderNotConfiguredError(f"{self.provider.value} write access is not configured")


class DisabledCalendarProvider:
    def __init__(self, provider: IntegrationProvider) -> None:
        self.provider = provider

    def list_events(self, *, start_at: datetime, end_at: datetime) -> list[CalendarEventSnapshot]:
        del start_at, end_at
        raise ProviderNotConfiguredError(f"{self.provider.value} read access is not configured")

    def create_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str:
        del event, idempotency_key
        raise ProviderNotConfiguredError(f"{self.provider.value} write access is not configured")

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

    def list_messages(self, *, since: datetime | None = None) -> list[NormalizedMessage]:
        return [
            message for message in self._messages if since is None or message.received_at >= since
        ]

    def send(self, draft: OutboundDraft, *, idempotency_key: str) -> str:
        self.sent.append((draft.id, idempotency_key))
        return f"fixture-message-{len(self.sent)}"


class FixtureCalendarProvider:
    """Sanitized replay adapter that records create/update calls without network access."""

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

    def create_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str:
        self.mutations.append(("create", idempotency_key))
        self.events.append(event)
        return f"fixture-event-{len(self.mutations)}"

    def update_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str:
        self.mutations.append(("update", idempotency_key))
        self.events = [
            event if current.provider_event_id == event.provider_event_id else current
            for current in self.events
        ]
        return event.provider_event_id
