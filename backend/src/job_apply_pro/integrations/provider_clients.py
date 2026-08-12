from __future__ import annotations

import base64
from collections.abc import Iterable
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import cast
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import SecretStr

from job_apply_pro.domain.communications import (
    CalendarEventSnapshot,
    IntegrationProvider,
    NormalizedMessage,
    OutboundDraft,
    ProviderSyncMode,
)
from job_apply_pro.integrations.communications import ProviderMessageBatch, ProviderMutationError
from job_apply_pro.integrations.oauth import AccessTokenProvider, OAuthAuthorizationError

MAX_PROVIDER_RESPONSE_BYTES = 5_000_000
MAX_PROVIDER_PAGES = 10
MAX_PROVIDER_ITEMS = 1_000
MAX_ATTACHMENT_PAGES = 5
MAX_ATTACHMENTS_PER_MESSAGE = 100
MAX_ATTACHMENT_NAME_CHARACTERS = 500
MAX_CONTINUATION_TOKEN_CHARACTERS = 8_000
MAX_GMAIL_MIME_PARTS = 500
MAX_ENCODED_MESSAGE_BODY_CHARACTERS = 200_000
MAX_MESSAGE_BODY_CHARACTERS = 100_000


def _json(response: httpx.Response, action: str) -> dict[str, object]:
    if response.status_code >= 400:
        raise ProviderMutationError(f"Provider {action} failed with HTTP {response.status_code}")
    if len(response.content) > MAX_PROVIDER_RESPONSE_BYTES:
        raise ProviderMutationError(f"Provider {action} response exceeded the byte limit")
    try:
        payload = response.json()
    except ValueError as error:
        raise ProviderMutationError(f"Provider {action} returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ProviderMutationError(f"Provider {action} returned an invalid response")
    return payload


def _collection(payload: dict[str, object], key: str, action: str) -> list[dict[str, object]]:
    values = payload.get(key, [])
    if not isinstance(values, list):
        raise ProviderMutationError(f"Provider {action} returned an invalid collection")
    return [value for value in values if isinstance(value, dict)]


def _google_collection(
    client: httpx.Client,
    *,
    url: str,
    params: dict[str, str | int],
    headers: dict[str, str],
    collection_key: str,
    action: str,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    page_params = dict(params)
    seen_tokens: set[str] = set()
    for _ in range(MAX_PROVIDER_PAGES):
        payload = _json(client.get(url, params=page_params, headers=headers), action)
        page_items = _collection(payload, collection_key, action)
        if len(items) + len(page_items) > MAX_PROVIDER_ITEMS:
            raise ProviderMutationError(f"Provider {action} exceeded the item limit")
        items.extend(page_items)
        token = payload.get("nextPageToken")
        if token is None:
            return items
        if (
            not isinstance(token, str)
            or not token
            or len(token) > MAX_CONTINUATION_TOKEN_CHARACTERS
        ):
            raise ProviderMutationError(f"Provider {action} returned an invalid page token")
        if token in seen_tokens:
            raise ProviderMutationError(f"Provider {action} returned a repeated page token")
        seen_tokens.add(token)
        page_params = {**params, "pageToken": token}
    raise ProviderMutationError(f"Provider {action} exceeded the page limit")


def _validated_graph_next_link(value: object, *, path_prefix: str, action: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_CONTINUATION_TOKEN_CHARACTERS:
        raise ProviderMutationError(f"Provider {action} returned an invalid next link")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise ProviderMutationError(f"Provider {action} returned an invalid next link") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != "graph.microsoft.com"
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.path != path_prefix
    ):
        raise ProviderMutationError(f"Provider {action} returned an untrusted next link")
    return value


def _graph_collection(
    client: httpx.Client,
    *,
    url: str,
    params: dict[str, str] | None,
    headers: dict[str, str],
    path_prefix: str,
    action: str,
    max_pages: int = MAX_PROVIDER_PAGES,
    max_items: int = MAX_PROVIDER_ITEMS,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    next_url = url
    next_params = params
    seen_links: set[str] = set()
    for _ in range(max_pages):
        payload = _json(client.get(next_url, params=next_params, headers=headers), action)
        page_items = _collection(payload, "value", action)
        if len(items) + len(page_items) > max_items:
            raise ProviderMutationError(f"Provider {action} exceeded the item limit")
        items.extend(page_items)
        next_link = _validated_graph_next_link(
            payload.get("@odata.nextLink"), path_prefix=path_prefix, action=action
        )
        if next_link is None:
            return items
        if next_link in seen_links:
            raise ProviderMutationError(f"Provider {action} returned a repeated next link")
        seen_links.add(next_link)
        next_url = next_link
        next_params = None
    raise ProviderMutationError(f"Provider {action} exceeded the page limit")


def _path_segment(value: object) -> str:
    return quote(str(value), safe="")


def _attachment_names(values: Iterable[object], action: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        name = value.strip()
        if not name or name in seen:
            continue
        if len(name) > MAX_ATTACHMENT_NAME_CHARACTERS:
            raise ProviderMutationError(f"Provider {action} attachment name exceeded the limit")
        seen.add(name)
        names.append(name)
        if len(names) > MAX_ATTACHMENTS_PER_MESSAGE:
            raise ProviderMutationError(f"Provider {action} exceeded the attachment limit")
    return names


def _token_headers(tokens: AccessTokenProvider, provider: IntegrationProvider) -> dict[str, str]:
    try:
        token = tokens.access_token(provider)
    except OAuthAuthorizationError as error:
        raise ProviderMutationError(str(error)) from error
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _decode_base64url(value: str) -> str:
    if len(value) > MAX_ENCODED_MESSAGE_BODY_CHARACTERS:
        raise ProviderMutationError("Provider Gmail message fetch body exceeded the limit")
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8", errors="replace")
    except (ValueError, TypeError) as error:
        raise ProviderMutationError(
            "Provider Gmail message fetch returned invalid body data"
        ) from error
    if len(decoded) > MAX_MESSAGE_BODY_CHARACTERS:
        raise ProviderMutationError("Provider Gmail message fetch body exceeded the limit")
    return decoded


def _gmail_payload_nodes(payload: dict[str, object]) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []
    pending = [payload]
    while pending:
        current = pending.pop()
        nodes.append(current)
        if len(nodes) > MAX_GMAIL_MIME_PARTS:
            raise ProviderMutationError("Provider Gmail message fetch exceeded the MIME part limit")
        parts = current.get("parts")
        if isinstance(parts, list):
            pending.extend(reversed([part for part in parts if isinstance(part, dict)]))
    return nodes


def _gmail_body(payload: dict[str, object]) -> str:
    nodes = _gmail_payload_nodes(payload)
    for node in [*filter(lambda item: item.get("mimeType") == "text/plain", nodes), *nodes]:
        body = node.get("body")
        if isinstance(body, dict) and isinstance(body.get("data"), str):
            value = _decode_base64url(str(body["data"]))
            if value:
                return value
    return ""


def _gmail_attachments(payload: dict[str, object]) -> list[str]:
    names = [node.get("filename") for node in _gmail_payload_nodes(payload)]
    return _attachment_names(names, "Gmail message fetch")


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
        items = _google_collection(
            self._client,
            url=f"{self._base}/messages",
            params=params,
            headers=_token_headers(self._tokens, self.provider),
            collection_key="messages",
            action="Gmail message listing",
        )
        return self._fetch_messages(
            [str(item["id"]) for item in items if isinstance(item.get("id"), str)]
        )

    def sync_messages(
        self, *, cursor: SecretStr | None, since: datetime | None = None
    ) -> ProviderMessageBatch:
        if cursor is None:
            return self._full_sync(since=since, mode=ProviderSyncMode.INITIAL)
        if since is not None:
            raise ValueError("A message synchronization time is allowed only before initial sync")
        history_id = cursor.get_secret_value()
        if not history_id.isdecimal() or len(history_id) > 100:
            raise ProviderMutationError("Stored Gmail synchronization state is invalid")
        params: dict[str, str | int] = {
            "startHistoryId": history_id,
            "historyTypes": "messageAdded",
            "maxResults": 500,
        }
        message_ids: list[str] = []
        seen_ids: set[str] = set()
        seen_tokens: set[str] = set()
        next_history_id: str | None = None
        for page_index in range(MAX_PROVIDER_PAGES):
            response = self._client.get(
                f"{self._base}/history",
                params=params,
                headers=_token_headers(self._tokens, self.provider),
            )
            if page_index == 0 and response.status_code == 404:
                return self._full_sync(since=None, mode=ProviderSyncMode.RECOVERY)
            payload = _json(response, "Gmail history listing")
            for history in _collection(payload, "history", "Gmail history listing"):
                additions = history.get("messagesAdded", [])
                if not isinstance(additions, list):
                    raise ProviderMutationError(
                        "Provider Gmail history listing returned an invalid collection"
                    )
                for addition in additions:
                    message = addition.get("message", {}) if isinstance(addition, dict) else {}
                    message_id = message.get("id") if isinstance(message, dict) else None
                    if isinstance(message_id, str) and message_id and message_id not in seen_ids:
                        seen_ids.add(message_id)
                        message_ids.append(message_id)
                        if len(message_ids) > MAX_PROVIDER_ITEMS:
                            raise ProviderMutationError(
                                "Provider Gmail history listing exceeded the item limit"
                            )
            returned_history_id = payload.get("historyId")
            if (
                not isinstance(returned_history_id, str)
                or not returned_history_id.isdecimal()
                or len(returned_history_id) > 100
            ):
                raise ProviderMutationError(
                    "Provider Gmail history listing returned invalid synchronization state"
                )
            next_history_id = returned_history_id
            token = payload.get("nextPageToken")
            if token is None:
                return ProviderMessageBatch(
                    messages=self._fetch_messages(message_ids),
                    cursor=SecretStr(next_history_id),
                    mode=ProviderSyncMode.INCREMENTAL,
                )
            if (
                not isinstance(token, str)
                or not token
                or len(token) > MAX_CONTINUATION_TOKEN_CHARACTERS
                or token in seen_tokens
            ):
                raise ProviderMutationError(
                    "Provider Gmail history listing returned an invalid or repeated page token"
                )
            seen_tokens.add(token)
            params = {**params, "pageToken": token}
        raise ProviderMutationError("Provider Gmail history listing exceeded the page limit")

    def _full_sync(self, *, since: datetime | None, mode: ProviderSyncMode) -> ProviderMessageBatch:
        profile = _json(
            self._client.get(
                f"{self._base}/profile",
                headers=_token_headers(self._tokens, self.provider),
            ),
            "Gmail profile fetch",
        )
        history_id = profile.get("historyId")
        if not isinstance(history_id, str) or not history_id.isdecimal() or len(history_id) > 100:
            raise ProviderMutationError(
                "Provider Gmail profile returned invalid synchronization state"
            )
        return ProviderMessageBatch(
            messages=self.list_messages(since=since),
            cursor=SecretStr(history_id),
            mode=mode,
        )

    def _fetch_messages(self, message_ids: Iterable[str]) -> list[NormalizedMessage]:
        messages: list[NormalizedMessage] = []
        seen_message_ids: set[str] = set()
        for message_id in message_ids:
            if message_id in seen_message_ids:
                continue
            seen_message_ids.add(message_id)
            response = self._client.get(
                f"{self._base}/messages/{_path_segment(message_id)}",
                params={"format": "full"},
                headers=_token_headers(self._tokens, self.provider),
            )
            if response.status_code == 404:
                continue
            raw = _json(response, "Gmail message fetch")
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
    _delta_path = "/v1.0/me/mailFolders/inbox/messages/delta"
    _delta_url = f"https://graph.microsoft.com{_delta_path}"

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
        values = _graph_collection(
            self._client,
            url=f"{self._base}/messages",
            params=params,
            headers=_token_headers(self._tokens, self.provider),
            path_prefix="/v1.0/me/messages",
            action="Outlook message listing",
        )
        return self._messages(values)

    def sync_messages(
        self, *, cursor: SecretStr | None, since: datetime | None = None
    ) -> ProviderMessageBatch:
        if cursor is not None and since is not None:
            raise ValueError("A message synchronization time is allowed only before initial sync")
        return self._delta_sync(
            cursor=cursor,
            since=since,
            mode=(ProviderSyncMode.INITIAL if cursor is None else ProviderSyncMode.INCREMENTAL),
            allow_recovery=True,
        )

    def _delta_sync(
        self,
        *,
        cursor: SecretStr | None,
        since: datetime | None,
        mode: ProviderSyncMode,
        allow_recovery: bool,
    ) -> ProviderMessageBatch:
        select_fields = (
            "id,conversationId,subject,bodyPreview,receivedDateTime,"
            "sender,toRecipients,hasAttachments"
        )
        params: dict[str, str] | None = None
        next_url = self._delta_url
        if cursor is None:
            params = {"$select": select_fields, "changeType": "created", "$top": "100"}
            if since is not None:
                params["$filter"] = f"receivedDateTime ge {since.astimezone(UTC).isoformat()}"
        else:
            next_url = self._validated_delta_link(cursor.get_secret_value())
        headers = _token_headers(self._tokens, self.provider)
        headers["Prefer"] = "odata.maxpagesize=100"
        values: list[dict[str, object]] = []
        seen_links: set[str] = set()
        delta_link: str | None = None
        for page_index in range(MAX_PROVIDER_PAGES):
            response = self._client.get(next_url, params=params, headers=headers)
            if cursor is not None and page_index == 0 and self._requires_delta_reset(response):
                if not allow_recovery:
                    raise ProviderMutationError("Outlook synchronization state reset failed")
                return self._delta_sync(
                    cursor=None,
                    since=None,
                    mode=ProviderSyncMode.RECOVERY,
                    allow_recovery=False,
                )
            payload = _json(response, "Outlook delta message listing")
            page_values = _collection(payload, "value", "Outlook delta message listing")
            if len(values) + len(page_values) > MAX_PROVIDER_ITEMS:
                raise ProviderMutationError(
                    "Provider Outlook delta message listing exceeded the item limit"
                )
            values.extend(page_values)
            next_link_value = payload.get("@odata.nextLink")
            if next_link_value is not None:
                next_link = self._validated_delta_link(next_link_value)
                if next_link in seen_links:
                    raise ProviderMutationError(
                        "Provider Outlook delta message listing returned a repeated next link"
                    )
                seen_links.add(next_link)
                next_url = next_link
                params = None
                continue
            delta_link = self._validated_delta_link(payload.get("@odata.deltaLink"))
            return ProviderMessageBatch(
                messages=self._messages(values),
                cursor=SecretStr(delta_link),
                mode=mode,
            )
        raise ProviderMutationError(
            "Provider Outlook delta message listing exceeded the page limit"
        )

    @classmethod
    def _validated_delta_link(cls, value: object) -> str:
        validated = _validated_graph_next_link(
            value,
            path_prefix=cls._delta_path,
            action="Outlook delta message listing",
        )
        if validated is None:
            raise ProviderMutationError(
                "Provider Outlook delta message listing did not return synchronization state"
            )
        return validated

    @staticmethod
    def _requires_delta_reset(response: httpx.Response) -> bool:
        if response.status_code == 410:
            return True
        if (
            response.status_code not in {400, 404}
            or len(response.content) > MAX_PROVIDER_RESPONSE_BYTES
        ):
            return False
        try:
            payload = response.json()
        except ValueError:
            return False
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = error.get("code") if isinstance(error, dict) else None
        return isinstance(code, str) and code.casefold() == "syncstatenotfound"

    def _messages(self, values: Iterable[dict[str, object]]) -> list[NormalizedMessage]:
        messages: list[NormalizedMessage] = []
        seen_message_ids: set[str] = set()
        for raw in values:
            message_id = raw.get("id")
            received_at = raw.get("receivedDateTime")
            if not isinstance(message_id, str) or not message_id or message_id in seen_message_ids:
                continue
            if not isinstance(received_at, str) or not received_at:
                continue
            seen_message_ids.add(message_id)
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
                    provider_message_id=message_id,
                    provider_thread_id=str(raw.get("conversationId", message_id)),
                    sender=(
                        str(sender_address.get("address", "unknown@example.invalid"))
                        if isinstance(sender_address, dict)
                        else "unknown@example.invalid"
                    ),
                    recipients=recipients,
                    subject=str(raw.get("subject", "")),
                    body_text=str(raw.get("bodyPreview", "")),
                    received_at=_parse_datetime(received_at),
                    attachment_names=(
                        self._attachment_names(message_id)
                        if raw.get("hasAttachments") is True
                        else []
                    ),
                )
            )
        return messages

    def _attachment_names(self, message_id: str) -> list[str]:
        path = f"/v1.0/me/messages/{_path_segment(message_id)}/attachments"
        values = _graph_collection(
            self._client,
            url=f"https://graph.microsoft.com{path}",
            params={"$select": "name,isInline,size"},
            headers=_token_headers(self._tokens, self.provider),
            path_prefix=path,
            action="Outlook attachment listing",
            max_pages=MAX_ATTACHMENT_PAGES,
            max_items=MAX_ATTACHMENTS_PER_MESSAGE,
        )
        return _attachment_names(
            [value.get("name") for value in values if value.get("isInline") is not True],
            "Outlook attachment listing",
        )

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
            f"{self._base}/messages/{_path_segment(message_id)}/send", headers=headers
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
        items = _google_collection(
            self._client,
            url=self._base,
            params={
                "timeMin": start_at.isoformat(),
                "timeMax": end_at.isoformat(),
                "singleEvents": "true",
                "showDeleted": "false",
                "maxResults": 250,
            },
            headers=_token_headers(self._tokens, self.provider),
            collection_key="items",
            action="Google Calendar event listing",
        )
        return [self._event(item) for item in items]

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
                f"{self._base}/{_path_segment(event.provider_event_id)}",
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
        start_value = start.get("dateTime") or start.get("date")
        end_value = end.get("dateTime") or end.get("date")
        if not start_value or not end_value:
            raise ProviderMutationError("Google Calendar event omitted its time interval")
        attendees = raw.get("attendees", [])
        attendee_items = attendees if isinstance(attendees, list) else []
        return CalendarEventSnapshot(
            provider_event_id=str(raw["id"]),
            title=str(raw.get("summary", "Calendar event")),
            start_at=_parse_datetime(str(start_value), str(start.get("timeZone", "UTC"))),
            end_at=_parse_datetime(str(end_value), str(end.get("timeZone", "UTC"))),
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
        values = _graph_collection(
            self._client,
            url="https://graph.microsoft.com/v1.0/me/calendarView",
            params={
                "startDateTime": start_at.isoformat(),
                "endDateTime": end_at.isoformat(),
                "$top": "250",
            },
            headers=_token_headers(self._tokens, self.provider),
            path_prefix="/v1.0/me/calendarView",
            action="Outlook Calendar event listing",
        )
        return [self._event(item) for item in values if item.get("isCancelled") is not True]

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
                f"{self._base}/{_path_segment(event.provider_event_id)}",
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
