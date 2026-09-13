from datetime import UTC, datetime

import pytest

from job_apply_pro.domain.communications import (
    IntegrationProvider,
    MailReplyContext,
    NormalizedMessage,
)
from job_apply_pro.domain.mail_threading import (
    build_reply_context,
    parse_gmail_reply_headers,
    parse_outlook_reply_headers,
    reply_context_fingerprint,
    validate_mailbox,
    validate_reply_context,
)


def gmail_headers(**changes: str) -> list[dict[str, str]]:
    values = {
        "From": '"Recruiter, Team" <recruiter@example.test>',
        "Subject": "Original subject",
        "Message-ID": "<parent@example.test>",
        "References": "<root@example.test>\r\n <previous@example.test>",
        "In-Reply-To": "<previous@example.test>",
        **changes,
    }
    return [{"name": name, "value": value} for name, value in values.items()]


def graph_source(**changes: object) -> dict[str, object]:
    return {
        "id": "AAMk+/opaque==",
        "conversationId": "conversation-1",
        "subject": "Original subject",
        "from": {"emailAddress": {"address": "recruiter@example.test"}},
        "sender": {"emailAddress": {"address": "recruiter@example.test"}},
        "replyTo": [],
        "internetMessageId": "<parent@example.test>",
        "receivedDateTime": "2026-09-13T12:00:00Z",
        "bodyPreview": "Readable correspondence",
        **changes,
    }


def source_message(provider: IntegrationProvider = IntegrationProvider.GMAIL) -> NormalizedMessage:
    return NormalizedMessage(
        provider=provider,
        provider_message_id="AAMk+/opaque=="
        if provider == IntegrationProvider.OUTLOOK
        else "gmail-1",
        provider_thread_id="thread-1",
        sender="recruiter@example.test",
        recipients=["owner@example.test"],
        subject="Original subject",
        body_text="Readable correspondence",
        received_at=datetime(2026, 9, 13, 12, tzinfo=UTC),
        reply_headers=(
            parse_gmail_reply_headers(gmail_headers())
            if provider == IntegrationProvider.GMAIL
            else parse_outlook_reply_headers(graph_source())
        ),
    )


def context_for(message: NormalizedMessage) -> MailReplyContext | None:
    return build_reply_context(
        message,
        record_id="record-1",
        account_key="a" * 64,
        account_label="owner@example.test",
        connection_fingerprint="b" * 64,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("owner@example.test", "owner@example.test"),
        ("Some.One+tag@EXAMPLE.TEST", "Some.One+tag@example.test"),
    ],
)
def test_single_ascii_mailbox_canonicalizes_only_domain(value: str, expected: str) -> None:
    assert validate_mailbox(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        " owner@example.test",
        "owner@example.test ",
        "Name <owner@example.test>",
        "owner@example.test,other@example.test",
        "Team: owner@example.test;",
        "a..b@example.test",
        ".owner@example.test",
        "owner.@example.test",
        "owner@-example.test",
        "owner@example..test",
        "owner@example.test\r\nBcc: other@example.test",
        "owner\u202e@example.test",
        "ownér@example.test",
        '"owner"@example.test',
        "owner@[127.0.0.1]",
        "a" * 65 + "@example.test",
        "owner@" + "a" * 64,
    ],
)
def test_unsupported_mailboxes_are_not_repaired(value: str) -> None:
    with pytest.raises(ValueError):
        validate_mailbox(value)


def test_gmail_headers_keep_bounded_rfc_facts_and_effective_reply_to() -> None:
    headers = parse_gmail_reply_headers(
        gmail_headers(**{"Reply-To": "Reply Team <reply@example.test>"})
    )
    assert headers is not None
    assert headers.from_address == headers.sender_address == "recruiter@example.test"
    assert headers.reply_to == ("reply@example.test",)
    assert headers.references == ("<root@example.test>", "<previous@example.test>")
    assert headers.in_reply_to == ("<previous@example.test>",)
    assert headers.rfc_message_id == "<parent@example.test>"
    context = context_for(source_message().model_copy(update={"reply_headers": headers}))
    assert context is not None
    assert context.recipient == "reply@example.test"
    assert context.references == (*headers.references, headers.rfc_message_id)
    assert context.subject == "Original subject"
    assert context.mime_reply_supported
    assert context.fingerprint == reply_context_fingerprint(context)


@pytest.mark.parametrize(
    "name", ["From", "Sender", "Reply-To", "Message-ID", "References", "In-Reply-To", "Subject"]
)
def test_duplicate_critical_headers_disable_reply(name: str) -> None:
    headers = gmail_headers(
        **{
            name: "recruiter@example.test"
            if name in {"Sender", "Reply-To"}
            else "<parent@example.test>"
        }
    )
    headers.append({"name": name.lower(), "value": headers[-1]["value"]})
    assert parse_gmail_reply_headers(headers) is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("From", "Team: recruiter@example.test;"),
        ("From", "a@example.test,b@example.test"),
        ("Reply-To", "a@example.test,b@example.test"),
        ("Reply-To", ""),
        ("Message-ID", "parent@example.test"),
        ("Message-ID", "<parent@example.test> <second@example.test>"),
        ("Message-ID", "<parent@example.test>\r\nBcc: someone@example.test"),
        ("Message-ID", "<párent@example.test>"),
        ("References", "<one@example.test>, <two@example.test>"),
        ("References", "<one@example.test>\n <two@example.test>"),
        ("References", " ".join(f"<id{i}@example.test>" for i in range(51))),
        ("In-Reply-To", "<one@example.test> <two@example.test>"),
        ("Subject", "Spoof\u202e review"),
        ("Subject", "a" * 1001),
    ],
)
def test_malformed_source_headers_disable_reply(name: str, value: str) -> None:
    assert parse_gmail_reply_headers(gmail_headers(**{name: value})) is None


def test_missing_gmail_id_disables_reply_and_chain_overflow_is_not_truncated() -> None:
    assert (
        parse_gmail_reply_headers([h for h in gmail_headers() if h["name"] != "Message-ID"]) is None
    )
    headers = parse_gmail_reply_headers(
        gmail_headers(References=" ".join(f"<id{i}@example.test>" for i in range(50)))
    )
    assert headers is not None
    assert context_for(source_message().model_copy(update={"reply_headers": headers})) is None


def test_missing_references_uses_one_in_reply_to_parent_and_empty_subject_is_exact() -> None:
    headers = parse_gmail_reply_headers([h for h in gmail_headers() if h["name"] != "References"])
    context = context_for(
        source_message().model_copy(update={"reply_headers": headers, "subject": ""})
    )
    assert context is not None
    assert context.subject == ""
    assert context.references == ("<previous@example.test>", "<parent@example.test>")


@pytest.mark.parametrize("field", ["from", "sender", "replyTo", "internetMessageId"])
def test_invalid_graph_critical_fields_disable_reply(field: str) -> None:
    assert parse_outlook_reply_headers(graph_source(**{field: "invalid"})) is None


def test_graph_json_allows_reply_to_but_mime_requires_address_agreement() -> None:
    headers = parse_outlook_reply_headers(
        graph_source(replyTo=[{"emailAddress": {"address": "reply@example.test"}}])
    )
    context = context_for(
        source_message(IntegrationProvider.OUTLOOK).model_copy(update={"reply_headers": headers})
    )
    assert context is not None and context.recipient == "reply@example.test"
    assert not context.mime_reply_supported
    direct = context_for(source_message(IntegrationProvider.OUTLOOK))
    assert direct is not None and direct.mime_reply_supported
    no_id = parse_outlook_reply_headers(graph_source(internetMessageId=None))
    context = context_for(
        source_message(IntegrationProvider.OUTLOOK).model_copy(update={"reply_headers": no_id})
    )
    assert context is not None and context.rfc_message_id is None


@pytest.mark.parametrize("field", ["provider_message_id", "provider_thread_id", "subject"])
def test_control_or_bidi_source_metadata_cannot_build_context(field: str) -> None:
    assert context_for(source_message().model_copy(update={field: "bad\u202econtext"})) is None


def test_provider_id_format_and_context_fingerprint_cannot_drift() -> None:
    message = source_message(IntegrationProvider.OUTLOOK)
    assert context_for(message.model_copy(update={"provider": IntegrationProvider.GMAIL})) is None
    context = context_for(message)
    assert context is not None
    with pytest.raises(ValueError):
        validate_reply_context(context.model_copy(update={"source_message_id": "another-message"}))
    assert (
        reply_context_fingerprint(context.model_copy(update={"fingerprint": "f" * 64}))
        == context.fingerprint
    )
