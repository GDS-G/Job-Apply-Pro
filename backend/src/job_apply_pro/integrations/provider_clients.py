from __future__ import annotations

import base64
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import cast
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from job_apply_pro.domain.communications import (
    CalendarEventSnapshot,
    IntegrationProvider,
    NormalizedMessage,
    OutboundDraft,
)
from job_apply_pro.integrations.communications import ProviderMutationError
from job_apply_pro.integrations.oauth import AccessTokenProvider, OAuthAuthorizationError


def _json(response: httpx.Response, action: str) -> dict[str, object]:
    if response.status_code >= 400:
        raise ProviderMutationError(f"Provider {action} failed with HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ProviderMutationError(f"Provider {action} returned an invalid response")
    return payload


def _token_headers(tokens: AccessTokenProvider, provider: IntegrationProvider) -> dict[str, str]:
    try:
        token = tokens.access_token(provider)
    except OAuthAuthorizationError as error:
        raise ProviderMutationError(str(error)) from error
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _decode_base64url(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8", errors="replace")


def _gmail_body(payload: dict[str, object]) -> str:
    body = payload.get("body")
    if isinstance(body, dict) and isinstance(body.get("data"), str):
        return _decode_base64url(str(body["data"]))
    parts = payload.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict) and part.get("mimeType") == "text/plain":
                value = _gmail_body(part)
                if value:
                    return value
        for part in parts:
            if isinstance(part, dict):
                value = _gmail_body(part)
                if value:
                    return value
    return ""


def _gmail_attachments(payload: dict[str, object]) -> list[str]:
    names: list[str] = []
    filename = payload.get("filename")
    if isinstance(filename, str) and filename:
        names.append(filename)
    parts = payload.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict):
                names.extend(_gmail_attachments(part))
    return names


def _parse_datetime(value: str, time_zone: str = "UTC") -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return parsed
    try:
        return parsed.replace(tzinfo=ZoneInfo(time_zone))
    except ZoneInfoNotFoundError:
        return parsed.replace(tzinfo=UTC)


class GmailMessageProvider:
    provider = IntegrationProvider.GMAIL
    _base = "https://gmail.googleapis.com/gmail/v1/users/me"

    def __init__(self, tokens: AccessTokenProvider, *, client: httpx.Client | None = None) -> None:
        self._tokens = tokens
        self._client = client or httpx.Client(timeout=30)

    def list_messages(self, *, since: datetime | None = None) -> list[NormalizedMessage]:
        params: dict[str, str | int] = {"maxResults": 100}
        if since is not None:
            params["q"] = f"after:{int(since.timestamp())}"
        payload = _json(
            self._client.get(
                f"{self._base}/messages",
                params=params,
                headers=_token_headers(self._tokens, self.provider),
            ),
            "Gmail message listing",
        )
        items = payload.get("messages", [])
        messages: list[NormalizedMessage] = []
        if not isinstance(items, list):
            return messages
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            raw = _json(
                self._client.get(
                    f"{self._base}/messages/{quote(str(item['id']))}",
                    params={"format": "full"},
                    headers=_token_headers(self._tokens, self.provider),
                ),
                "Gmail message fetch",
            )
            message_payload = raw.get("payload", {})
            if not isinstance(message_payload, dict):
                continue
            header_items = message_payload.get("headers", [])
            headers = (
                {
                    str(header.get("name", "")).casefold(): str(header.get("value", ""))
                    for header in header_items
                    if isinstance(header, dict)
                }
                if isinstance(header_items, list)
                else {}
            )
            recipients = [value.strip() for value in headers.get("to", "").split(",") if value]
            internal_date = raw.get("internalDate")
            received_at = (
                datetime.fromtimestamp(int(str(internal_date)) / 1_000, tz=UTC)
                if internal_date is not None
                else datetime.now(UTC)
            )
            messages.append(
                NormalizedMessage(
                    provider=self.provider,
                    provider_message_id=str(raw["id"]),
                    provider_thread_id=str(raw.get("threadId", raw["id"])),
                    sender=headers.get("from", "unknown@example.invalid"),
                    recipients=recipients,
                    subject=headers.get("subject", ""),
                    body_text=_gmail_body(message_payload),
                    received_at=received_at,
                    attachment_names=_gmail_attachments(message_payload),
                )
            )
        return messages

    def send(self, draft: OutboundDraft, *, idempotency_key: str) -> str:
        message = EmailMessage()
        message["To"] = draft.recipient
        message["Subject"] = draft.subject
        message["X-Job-Apply-Pro-Idempotency-Key"] = idempotency_key
        message.set_content(draft.body_text)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        payload = _json(
            self._client.post(
                f"{self._base}/messages/send",
                json={"raw": raw, "threadId": draft.provider_thread_id},
                headers=_token_headers(self._tokens, self.provider),
            ),
            "Gmail send",
        )
        message_id = payload.get("id")
        if not isinstance(message_id, str) or not message_id:
            raise ProviderMutationError("Gmail send did not return a message identifier")
        return message_id


class OutlookMessageProvider:
    provider = IntegrationProvider.OUTLOOK
    _base = "https://graph.microsoft.com/v1.0/me"

    def __init__(self, tokens: AccessTokenProvider, *, client: httpx.Client | None = None) -> None:
        self._tokens = tokens
        self._client = client or httpx.Client(timeout=30)

    def list_messages(self, *, since: datetime | None = None) -> list[NormalizedMessage]:
        params: dict[str, str] = {
            "$top": "100",
            "$select": (
                "id,conversationId,subject,bodyPreview,receivedDateTime,"
                "sender,toRecipients,hasAttachments"
            ),
        }
        if since is not None:
            params["$filter"] = f"receivedDateTime ge {since.astimezone(UTC).isoformat()}"
        payload = _json(
            self._client.get(
                f"{self._base}/messages",
                params=params,
                headers=_token_headers(self._tokens, self.provider),
            ),
            "Outlook message listing",
        )
        values = payload.get("value", [])
        if not isinstance(values, list):
            return []
        messages: list[NormalizedMessage] = []
        for raw in values:
            if not isinstance(raw, dict):
                continue
            sender = raw.get("sender", {})
            sender_address = sender.get("emailAddress", {}) if isinstance(sender, dict) else {}
            to_items = raw.get("toRecipients", [])
            recipients = []
            if isinstance(to_items, list):
                for recipient in to_items:
                    address = (
                        recipient.get("emailAddress", {}) if isinstance(recipient, dict) else {}
                    )
                    if isinstance(address, dict) and isinstance(address.get("address"), str):
                        recipients.append(str(address["address"]))
            messages.append(
                NormalizedMessage(
                    provider=self.provider,
                    provider_message_id=str(raw["id"]),
                    provider_thread_id=str(raw.get("conversationId", raw["id"])),
                    sender=(
                        str(sender_address.get("address", "unknown@example.invalid"))
                        if isinstance(sender_address, dict)
                        else "unknown@example.invalid"
                    ),
                    recipients=recipients,
                    subject=str(raw.get("subject", "")),
                    body_text=str(raw.get("bodyPreview", "")),
                    received_at=_parse_datetime(str(raw["receivedDateTime"])),
                )
            )
        return messages

    def send(self, draft: OutboundDraft, *, idempotency_key: str) -> str:
        headers = _token_headers(self._tokens, self.provider)
        headers["X-Job-Apply-Pro-Idempotency-Key"] = idempotency_key
        created = _json(
            self._client.post(
                f"{self._base}/messages",
                json={
                    "subject": draft.subject,
                    "body": {"contentType": "Text", "content": draft.body_text},
                    "toRecipients": [{"emailAddress": {"address": draft.recipient}}],
                },
                headers=headers,
            ),
            "Outlook draft creation",
        )
        message_id = created.get("id")
        if not isinstance(message_id, str) or not message_id:
            raise ProviderMutationError("Outlook draft did not return a message identifier")
        response = self._client.post(
            f"{self._base}/messages/{quote(message_id)}/send", headers=headers
        )
        if response.status_code >= 400:
            raise ProviderMutationError(f"Outlook send failed with HTTP {response.status_code}")
        return message_id


class GoogleCalendarProvider:
    provider = IntegrationProvider.GOOGLE_CALENDAR
    _base = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

    def __init__(self, tokens: AccessTokenProvider, *, client: httpx.Client | None = None) -> None:
        self._tokens = tokens
        self._client = client or httpx.Client(timeout=30)

    def list_events(self, *, start_at: datetime, end_at: datetime) -> list[CalendarEventSnapshot]:
        payload = _json(
            self._client.get(
                self._base,
                params={
                    "timeMin": start_at.isoformat(),
                    "timeMax": end_at.isoformat(),
                    "singleEvents": "true",
                    "maxResults": 250,
                },
                headers=_token_headers(self._tokens, self.provider),
            ),
            "Google Calendar event listing",
        )
        items = payload.get("items", [])
        return (
            [self._event(item) for item in items if isinstance(item, dict)]
            if isinstance(items, list)
            else []
        )

    def create_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str:
        payload = _json(
            self._client.post(
                self._base,
                json=self._payload(event),
                headers={
                    **_token_headers(self._tokens, self.provider),
                    "X-Job-Apply-Pro-Idempotency-Key": idempotency_key,
                },
            ),
            "Google Calendar event creation",
        )
        return self._identifier(payload, "Google Calendar create")

    def update_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str:
        payload = _json(
            self._client.put(
                f"{self._base}/{quote(event.provider_event_id)}",
                json=self._payload(event),
                headers={
                    **_token_headers(self._tokens, self.provider),
                    "X-Job-Apply-Pro-Idempotency-Key": idempotency_key,
                },
            ),
            "Google Calendar event update",
        )
        return self._identifier(payload, "Google Calendar update")

    @staticmethod
    def _event(raw: dict[str, object]) -> CalendarEventSnapshot:
        start = cast(dict[str, object], raw.get("start", {}))
        end = cast(dict[str, object], raw.get("end", {}))
        attendees = raw.get("attendees", [])
        attendee_items = attendees if isinstance(attendees, list) else []
        return CalendarEventSnapshot(
            provider_event_id=str(raw["id"]),
            title=str(raw.get("summary", "Calendar event")),
            start_at=_parse_datetime(str(start["dateTime"]), str(start.get("timeZone", "UTC"))),
            end_at=_parse_datetime(str(end["dateTime"]), str(end.get("timeZone", "UTC"))),
            time_zone=str(start.get("timeZone", "UTC")),
            attendees=[
                str(item["email"])
                for item in attendee_items
                if isinstance(item, dict) and item.get("email")
            ],
            conferencing_url=str(raw["hangoutLink"]) if raw.get("hangoutLink") else None,
            location=str(raw["location"]) if raw.get("location") else None,
        )

    @staticmethod
    def _payload(event: CalendarEventSnapshot) -> dict[str, object]:
        return {
            "summary": event.title,
            "start": {"dateTime": event.start_at.isoformat(), "timeZone": event.time_zone},
            "end": {"dateTime": event.end_at.isoformat(), "timeZone": event.time_zone},
            "attendees": [{"email": value} for value in event.attendees],
            "location": event.location,
        }

    @staticmethod
    def _identifier(payload: dict[str, object], action: str) -> str:
        value = payload.get("id")
        if not isinstance(value, str) or not value:
            raise ProviderMutationError(f"{action} did not return an event identifier")
        return value


class OutlookCalendarProvider:
    provider = IntegrationProvider.OUTLOOK_CALENDAR
    _base = "https://graph.microsoft.com/v1.0/me/events"

    def __init__(self, tokens: AccessTokenProvider, *, client: httpx.Client | None = None) -> None:
        self._tokens = tokens
        self._client = client or httpx.Client(timeout=30)

    def list_events(self, *, start_at: datetime, end_at: datetime) -> list[CalendarEventSnapshot]:
        payload = _json(
            self._client.get(
                "https://graph.microsoft.com/v1.0/me/calendarView",
                params={"startDateTime": start_at.isoformat(), "endDateTime": end_at.isoformat()},
                headers=_token_headers(self._tokens, self.provider),
            ),
            "Outlook Calendar event listing",
        )
        values = payload.get("value", [])
        return (
            [self._event(item) for item in values if isinstance(item, dict)]
            if isinstance(values, list)
            else []
        )

    def create_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str:
        payload = _json(
            self._client.post(
                self._base,
                json=self._payload(event),
                headers={
                    **_token_headers(self._tokens, self.provider),
                    "X-Job-Apply-Pro-Idempotency-Key": idempotency_key,
                },
            ),
            "Outlook Calendar event creation",
        )
        return self._identifier(payload, "Outlook Calendar create")

    def update_event(self, event: CalendarEventSnapshot, *, idempotency_key: str) -> str:
        payload = _json(
            self._client.patch(
                f"{self._base}/{quote(event.provider_event_id)}",
                json=self._payload(event),
                headers={
                    **_token_headers(self._tokens, self.provider),
                    "X-Job-Apply-Pro-Idempotency-Key": idempotency_key,
                },
            ),
            "Outlook Calendar event update",
        )
        return self._identifier(payload, "Outlook Calendar update")

    @staticmethod
    def _event(raw: dict[str, object]) -> CalendarEventSnapshot:
        start = cast(dict[str, object], raw.get("start", {}))
        end = cast(dict[str, object], raw.get("end", {}))
        attendees = raw.get("attendees", [])
        online = raw.get("onlineMeeting", {})
        location = raw.get("location", {})
        return CalendarEventSnapshot(
            provider_event_id=str(raw["id"]),
            title=str(raw.get("subject", "Calendar event")),
            start_at=_parse_datetime(str(start["dateTime"]), str(start.get("timeZone", "UTC"))),
            end_at=_parse_datetime(str(end["dateTime"]), str(end.get("timeZone", "UTC"))),
            time_zone=str(start.get("timeZone", "UTC")),
            attendees=[
                str(cast(dict[str, object], item.get("emailAddress", {})).get("address"))
                for item in attendees
                if isinstance(item, dict)
                and cast(dict[str, object], item.get("emailAddress", {})).get("address")
            ]
            if isinstance(attendees, list)
            else [],
            conferencing_url=(
                str(online.get("joinUrl"))
                if isinstance(online, dict) and online.get("joinUrl")
                else None
            ),
            location=(
                str(location.get("displayName"))
                if isinstance(location, dict) and location.get("displayName")
                else None
            ),
        )

    @staticmethod
    def _payload(event: CalendarEventSnapshot) -> dict[str, object]:
        return {
            "subject": event.title,
            "start": {"dateTime": event.start_at.isoformat(), "timeZone": event.time_zone},
            "end": {"dateTime": event.end_at.isoformat(), "timeZone": event.time_zone},
            "attendees": [
                {"emailAddress": {"address": value}, "type": "required"}
                for value in event.attendees
            ],
            "location": {"displayName": event.location} if event.location else None,
        }

    @staticmethod
    def _identifier(payload: dict[str, object], action: str) -> str:
        value = payload.get("id")
        if not isinstance(value, str) or not value:
            raise ProviderMutationError(f"{action} did not return an event identifier")
        return value
