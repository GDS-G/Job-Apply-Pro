"""Bounded reply metadata; unsupported header syntax never becomes a guessed reply."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from email.errors import HeaderParseError
from email.headerregistry import AddressHeader, HeaderRegistry

from job_apply_pro.domain.communications import (
    IntegrationProvider,
    MailReplyContext,
    MailReplyHeaders,
    NormalizedMessage,
)

_ATOM = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
_DOT_ATOM = rf"{_ATOM}(?:\.{_ATOM})*"
_MAILBOX = re.compile(rf"({_DOT_ATOM})@([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)")
_MESSAGE_ID = re.compile(rf"<{_DOT_ATOM}@{_DOT_ATOM}>")
_HEX = re.compile(r"[a-f0-9]{64}")
_MAX_HEADER_BYTES = 8_192
_CRITICAL_GMAIL_HEADERS = {
    "from",
    "sender",
    "reply-to",
    "message-id",
    "references",
    "in-reply-to",
    "subject",
}


def _safe_text(value: object, limit: int, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value)
        or any(unicodedata.category(character).startswith("C") for character in value)
        or any(character in "\u2028\u2029" for character in value)
    ):
        raise ValueError("Mail reply metadata is not supported")
    return value


def validate_mailbox(value: str) -> str:
    """Accept one plain ASCII dot-atom mailbox; never repair or select an address."""
    value = _safe_text(value, 254)
    match = _MAILBOX.fullmatch(value)
    if match is None or len(match[1]) > 64:
        raise ValueError("Review one supported email address")
    domain = match[2]
    if len(domain) > 253 or any(
        not 1 <= len(label) <= 63 or label.startswith("-") or label.endswith("-")
        for label in domain.split(".")
    ):
        raise ValueError("Review one supported email address")
    return f"{match[1]}@{domain.lower()}"


def _unfold(value: object, limit: int = _MAX_HEADER_BYTES) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("Mail source header is not supported")
    # Only RFC folding is admitted; lone newlines and injected header lines fail.
    return _safe_text(re.sub(r"\r\n[ \t]+", " ", value).replace("\t", " "), limit).strip()


def _source_mailbox(value: object) -> str:
    unfolded = _unfold(value, 1_000)
    parsed = HeaderRegistry()("From", unfolded)
    if (
        not isinstance(parsed, AddressHeader)
        or parsed.defects
        or len(parsed.addresses) != 1
        or any(group.display_name is not None for group in parsed.groups)
    ):
        raise ValueError("Mail source address is not supported")
    return validate_mailbox(parsed.addresses[0].addr_spec)


def _message_id(value: object) -> str:
    # Leave room for "In-Reply-To: " on an RFC 5322 line (998 octets).
    unfolded = _unfold(value, 985)
    if _MESSAGE_ID.fullmatch(unfolded) is None:
        raise ValueError("Mail source message identifier is not supported")
    return unfolded


def _references(value: object, *, maximum: int = 50) -> tuple[str, ...]:
    unfolded = _unfold(value)
    parts = unfolded.split(" ")
    values = tuple(_message_id(part) for part in parts if part)
    if not values or len(values) > maximum:
        raise ValueError("Mail source reference chain is not supported")
    return values


def parse_gmail_reply_headers(headers: object) -> MailReplyHeaders | None:
    try:
        if not isinstance(headers, list) or len(headers) > 200:
            return None
        critical: dict[str, str] = {}
        for header in headers:
            if not isinstance(header, dict) or not isinstance(header.get("name"), str):
                return None
            name = header["name"].casefold()
            if name not in _CRITICAL_GMAIL_HEADERS:
                continue
            if name in critical or not isinstance(header.get("value"), str):
                return None
            critical[name] = header["value"]
        from_address = _source_mailbox(critical.get("from"))
        # An empty source subject is valid; it must still be preserved exactly.
        _safe_text(critical.get("subject", ""), 1_000, empty=True)
        return MailReplyHeaders(
            source_id_format="GMAIL",
            from_address=from_address,
            sender_address=(
                _source_mailbox(critical["sender"]) if "sender" in critical else from_address
            ),
            reply_to=((_source_mailbox(critical["reply-to"]),) if "reply-to" in critical else ()),
            rfc_message_id=_message_id(critical.get("message-id")),
            references=_references(critical["references"]) if "references" in critical else (),
            in_reply_to=(
                _references(critical["in-reply-to"], maximum=1) if "in-reply-to" in critical else ()
            ),
        )
    except (ValueError, TypeError, IndexError, HeaderParseError):
        return None


def _graph_address(value: object) -> str:
    if not isinstance(value, dict):
        raise ValueError("Mail source address is not supported")
    mailbox = value.get("emailAddress")
    if not isinstance(mailbox, dict):
        raise ValueError("Mail source address is not supported")
    address = mailbox.get("address")
    if not isinstance(address, str):
        raise ValueError("Mail source address is not supported")
    return validate_mailbox(address)


def parse_outlook_reply_headers(raw: dict[str, object]) -> MailReplyHeaders | None:
    try:
        reply_to = raw.get("replyTo", [])
        if not isinstance(reply_to, list) or len(reply_to) > 1:
            return None
        internet_id = raw.get("internetMessageId")
        _safe_text(raw.get("subject", ""), 1_000, empty=True)
        return MailReplyHeaders(
            source_id_format="GRAPH_IMMUTABLE",
            from_address=_graph_address(raw.get("from")),
            sender_address=_graph_address(raw.get("sender")),
            reply_to=tuple(_graph_address(value) for value in reply_to),
            rfc_message_id=_message_id(internet_id) if internet_id is not None else None,
        )
    except (ValueError, TypeError, IndexError):
        return None


def reply_context_fingerprint(context: MailReplyContext) -> str:
    return hashlib.sha256(
        json.dumps(
            context.model_dump(mode="json", exclude={"fingerprint"}),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()


def validate_reply_context(context: MailReplyContext) -> None:
    """Recheck typed/model-copy callers before encoding any provider mutation."""
    _safe_text(context.source_record_id, 100)
    _safe_text(context.source_message_id, 500)
    _safe_text(context.source_thread_id, 500)
    if any(
        character.isspace()
        for value in (context.source_record_id, context.source_message_id, context.source_thread_id)
        for character in value
    ):
        raise ValueError("Mail reply identifiers are not supported")
    _safe_text(context.subject, 1_000, empty=True)
    if (
        context.policy_version != "mail-reply-v1"
        or not _HEX.fullmatch(context.account_key)
        or not _HEX.fullmatch(context.connection_fingerprint)
        or validate_mailbox(context.account_label) != context.account_label
        or validate_mailbox(context.recipient) != context.recipient
        or context.provider not in {IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK}
        or context.source_id_format
        != ("GMAIL" if context.provider == IntegrationProvider.GMAIL else "GRAPH_IMMUTABLE")
        or not isinstance(context.mime_reply_supported, bool)
        or len(context.references) > 50
        or len(" ".join(context.references)) > _MAX_HEADER_BYTES
    ):
        raise ValueError("Mail reply context is not supported")
    if context.rfc_message_id is not None:
        _message_id(context.rfc_message_id)
    for reference in context.references:
        _message_id(reference)
    if context.provider == IntegrationProvider.GMAIL and (
        context.rfc_message_id is None
        or not context.references
        or context.references[-1] != context.rfc_message_id
        or not context.mime_reply_supported
    ):
        raise ValueError("Gmail reply context is not supported")
    if reply_context_fingerprint(context) != context.fingerprint:
        raise ValueError("Mail reply context changed after review")


def build_reply_context(
    message: NormalizedMessage,
    *,
    record_id: str,
    account_key: str,
    account_label: str,
    connection_fingerprint: str,
) -> MailReplyContext | None:
    try:
        headers = message.reply_headers
        if headers is None:
            return None
        from_address = validate_mailbox(headers.from_address)
        sender_address = validate_mailbox(headers.sender_address)
        if len(headers.reply_to) > 1:
            return None
        recipient = validate_mailbox(headers.reply_to[0]) if headers.reply_to else from_address
        references = headers.references or headers.in_reply_to
        if headers.rfc_message_id is not None:
            references = (*references, headers.rfc_message_id)
        context = MailReplyContext(
            provider=message.provider,
            account_key=account_key,
            account_label=validate_mailbox(account_label),
            connection_fingerprint=connection_fingerprint,
            source_record_id=record_id,
            source_message_id=message.provider_message_id,
            source_thread_id=message.provider_thread_id,
            source_id_format=headers.source_id_format,
            recipient=recipient,
            subject=message.subject,
            rfc_message_id=headers.rfc_message_id,
            references=references,
            mime_reply_supported=(
                message.provider == IntegrationProvider.GMAIL
                or sender_address == from_address == recipient
            ),
            fingerprint="0" * 64,
        )
        context = context.model_copy(update={"fingerprint": reply_context_fingerprint(context)})
        validate_reply_context(context)
        return context
    except (ValueError, TypeError, AttributeError):
        return None
