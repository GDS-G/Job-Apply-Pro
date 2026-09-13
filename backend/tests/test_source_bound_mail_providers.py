import base64
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from email import policy
from email.message import Message
from email.parser import BytesParser
from io import BytesIO

import httpx
import pytest
from pydantic import SecretStr
from pypdf import PdfWriter

from job_apply_pro.domain.communications import (
    IntegrationProvider,
    MailAttachmentManifest,
    MailAttachmentMetadata,
    MailMode,
    MessageCategory,
    OutboundDraft,
    OutboundPolicy,
)
from job_apply_pro.domain.mail import MailAttachmentError, VerifiedMailAttachment
from job_apply_pro.domain.mail_threading import (
    parse_gmail_reply_headers,
    parse_outlook_reply_headers,
    reply_context_fingerprint,
)
from job_apply_pro.integrations.communications import (
    ProviderMutationError,
    ProviderSendUncertainError,
    normalize_gmail_message,
    normalize_outlook_message,
)
from job_apply_pro.integrations.provider_clients import GmailMessageProvider, OutlookMessageProvider
from test_mail_threading import context_for, gmail_headers, graph_source, source_message

MAIL_PROVIDERS = (IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK)


class Tokens:
    def __init__(self) -> None:
        self.calls = 0

    def access_token(self, provider: IntegrationProvider) -> str:
        assert provider in MAIL_PROVIDERS
        self.calls += 1
        return "synthetic-mail-token"


def draft_for(provider: IntegrationProvider, *, reply: bool = True) -> OutboundDraft:
    context = context_for(source_message(provider)) if reply else None
    return OutboundDraft(
        id="draft-1",
        analysis_id="record-1",
        provider=provider,
        provider_thread_id=context.source_thread_id if context else "",
        recipient=context.recipient if context else "new-recipient@example.test",
        subject=context.subject if context else "Standalone message",
        body_text="Exact reviewed plain text.\nSecond line.",
        category=MessageCategory.RECRUITER_INQUIRY,
        policy=OutboundPolicy.REVIEW_REQUIRED,
        document_version_ids=[],
        mode=MailMode.REPLY if reply else MailMode.NEW_MESSAGE,
        account_key="a" * 64,
        account_label="owner@example.test",
        reply_context=context,
        provider_binding_fingerprint=context.connection_fingerprint if context else "b" * 64,
        fingerprint="d" * 64,
        created_at=datetime(2026, 9, 13, 12, tzinfo=UTC),
        updated_at=datetime(2026, 9, 13, 12, tzinfo=UTC),
    )


def attach(draft: OutboundDraft) -> tuple[OutboundDraft, tuple[VerifiedMailAttachment, ...]]:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(output)
    data = output.getvalue()
    metadata = MailAttachmentMetadata(
        document_version_id="version-1",
        document_id="document-1",
        file_name="reviewed.pdf",
        media_type="application/pdf",
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )
    return draft.model_copy(
        update={
            "workflow_id": "workflow-1",
            "document_version_ids": [metadata.document_version_id],
            "attachment_manifest": MailAttachmentManifest(
                profile_id="profile-1", attachments=(metadata,)
            ),
        }
    ), (VerifiedMailAttachment(metadata, data),)


def adapter_for(
    provider: IntegrationProvider,
    tokens: Tokens,
    handler: Callable[[httpx.Request], httpx.Response],
) -> GmailMessageProvider | OutlookMessageProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return (
        GmailMessageProvider(tokens, client=client)
        if provider == IntegrationProvider.GMAIL
        else OutlookMessageProvider(tokens, client=client)
    )


def gmail_mime(request: httpx.Request) -> Message:
    raw = json.loads(request.content)["raw"]
    return BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    )


@pytest.mark.parametrize("has_attachments", [False, True])
def test_gmail_one_shot_reply_has_exact_rfc_thread_subject_and_attachments(
    has_attachments: bool,
) -> None:
    draft = draft_for(IntegrationProvider.GMAIL)
    attachments: tuple[VerifiedMailAttachment, ...] = ()
    if has_attachments:
        draft, attachments = attach(draft)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/gmail/v1/users/me/messages/send"
        assert request.headers["Authorization"] == "Bearer synthetic-mail-token"
        assert json.loads(request.content)["threadId"] == "thread-1"
        message = gmail_mime(request)
        assert message["From"] == draft.account_label
        assert message["To"] == draft.recipient
        assert message["Subject"] == "Original subject"
        assert message["In-Reply-To"] == "<parent@example.test>"
        assert str(message["References"]).split() == [
            "<root@example.test>",
            "<previous@example.test>",
            "<parent@example.test>",
        ]
        found = [part for part in message.walk() if part.get_content_disposition() == "attachment"]
        assert [part.get_payload(decode=True) for part in found] == [
            item.data for item in attachments
        ]
        return httpx.Response(200, json={"id": "sent-1"})

    result = adapter_for(IntegrationProvider.GMAIL, Tokens(), handler).send(
        draft, idempotency_key="synthetic-key-1", attachments=attachments
    )
    assert result.provider_resource_id == "sent-1"
    assert len(requests) == 1


def test_gmail_new_message_omits_all_thread_linkage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "threadId" not in json.loads(request.content)
        message = gmail_mime(request)
        assert message["In-Reply-To"] is None and message["References"] is None
        assert message["Subject"] == "Standalone message"
        return httpx.Response(200, json={"id": "new-1"})

    adapter_for(IntegrationProvider.GMAIL, Tokens(), handler).send(
        draft_for(IntegrationProvider.GMAIL, reply=False), idempotency_key="new-message-key"
    )


def test_long_gmail_message_id_remains_literal_rfc_syntax_on_wire() -> None:
    message_id = "<" + "a" * 950 + "@example.test>"
    headers = parse_gmail_reply_headers(gmail_headers(**{"Message-ID": message_id}))
    context = context_for(source_message().model_copy(update={"reply_headers": headers}))
    assert context is not None
    draft = draft_for(IntegrationProvider.GMAIL).model_copy(update={"reply_context": context})

    def handler(request: httpx.Request) -> httpx.Response:
        raw = json.loads(request.content)["raw"]
        encoded_message = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        message = gmail_mime(request)
        assert message["In-Reply-To"] == message_id
        assert str(message["References"]).split()[-1] == message_id
        assert all(len(line) <= 998 for line in encoded_message.split(b"\r\n"))
        assert "=?" not in str(message["In-Reply-To"])
        return httpx.Response(200, json={"id": "sent-long-parent"})

    adapter_for(IntegrationProvider.GMAIL, Tokens(), handler).send(
        draft, idempotency_key="long-parent-key"
    )


def test_graph_json_reply_uses_encoded_immutable_source_exact_recipient_and_text() -> None:
    source = source_message(IntegrationProvider.OUTLOOK).model_copy(
        update={
            "reply_headers": parse_outlook_reply_headers(
                graph_source(
                    replyTo=[{"emailAddress": {"address": "reply@example.test"}}],
                    internetMessageId=None,
                )
            )
        }
    )
    context = context_for(source)
    assert context is not None and not context.mime_reply_supported
    draft = draft_for(IntegrationProvider.OUTLOOK).model_copy(
        update={
            "reply_context": context,
            "recipient": context.recipient,
        }
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.url.raw_path == b"/v1.0/me/messages/AAMk%2B%2Fopaque%3D%3D/reply"
        assert request.headers["Prefer"] == 'IdType="ImmutableId"'
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {
            "message": {
                "subject": draft.subject,
                "body": {"contentType": "Text", "content": draft.body_text},
                "toRecipients": [{"emailAddress": {"address": "reply@example.test"}}],
                "ccRecipients": [],
                "bccRecipients": [],
            }
        }
        return httpx.Response(202)

    assert (
        adapter_for(IntegrationProvider.OUTLOOK, Tokens(), handler)
        .send(draft, idempotency_key="graph-reply-key")
        .provider_resource_id
        is None
    )
    assert len(requests) == 1


def test_graph_mime_reply_contains_exact_attachment_bytes_and_no_remote_draft() -> None:
    draft, attachments = attach(draft_for(IntegrationProvider.OUTLOOK))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST" and request.url.path.endswith("/reply")
        assert request.headers["Content-Type"] == "text/plain"
        assert request.headers["Prefer"] == 'IdType="ImmutableId"'
        message = BytesParser(policy=policy.default).parsebytes(
            base64.b64decode(request.content, validate=True)
        )
        assert message["To"] == draft.recipient
        assert message["Subject"] == draft.subject
        assert message["In-Reply-To"] == "<parent@example.test>"
        found = [part for part in message.walk() if part.get_content_disposition() == "attachment"]
        assert [part.get_payload(decode=True) for part in found] == [attachments[0].data]
        assert found[0].get_filename() == "reviewed.pdf"
        return httpx.Response(202)

    adapter_for(IntegrationProvider.OUTLOOK, Tokens(), handler).send(
        draft, idempotency_key="mime-reply-key", attachments=attachments
    )
    assert len(requests) == 1


@pytest.mark.parametrize("changed", ["replyTo", "sender"])
def test_graph_mime_reply_refuses_recipient_disagreement_before_token_or_post(changed: str) -> None:
    update: object = {"emailAddress": {"address": "different@example.test"}}
    if changed == "replyTo":
        update = [update]
    context = context_for(
        source_message(IntegrationProvider.OUTLOOK).model_copy(
            update={
                "reply_headers": parse_outlook_reply_headers(graph_source(**{changed: update})),
            }
        )
    )
    assert context is not None and not context.mime_reply_supported
    draft, attachments = attach(
        draft_for(IntegrationProvider.OUTLOOK).model_copy(
            update={
                "reply_context": context,
                "recipient": context.recipient,
            }
        )
    )
    tokens = Tokens()
    with pytest.raises(ProviderMutationError, match="safely target"):
        adapter_for(
            IntegrationProvider.OUTLOOK, tokens, lambda _: pytest.fail("No provider POST")
        ).send(draft, idempotency_key="unsafe-mime-key", attachments=attachments)
    assert tokens.calls == 0


@pytest.mark.parametrize("provider", MAIL_PROVIDERS)
@pytest.mark.parametrize(
    "changes",
    [
        {"mode": None},
        {"account_key": None},
        {"account_label": "Name <owner@example.test>"},
        {"account_label": "ownér@example.test"},
        {"recipient": "one@example.test,two@example.test"},
        {"reply_context": None},
        {"provider_thread_id": "other-thread"},
        {"analysis_id": "other-record"},
        {"subject": "Edited reply subject"},
        {"mode": MailMode.NEW_MESSAGE},
    ],
)
def test_direct_send_rejects_legacy_or_changed_binding_before_tokens(
    provider: IntegrationProvider, changes: dict[str, object]
) -> None:
    tokens = Tokens()
    with pytest.raises(ProviderMutationError):
        adapter_for(provider, tokens, lambda _: pytest.fail("No provider POST")).send(
            draft_for(provider).model_copy(update=changes), idempotency_key="invalid-context-key"
        )
    assert tokens.calls == 0


@pytest.mark.parametrize("provider", MAIL_PROVIDERS)
def test_context_tampering_without_a_new_fingerprint_is_not_sent(
    provider: IntegrationProvider,
) -> None:
    draft = draft_for(provider)
    assert draft.reply_context is not None
    context = draft.reply_context.model_copy(update={"source_message_id": "changed-source"})
    tokens = Tokens()
    with pytest.raises(ProviderMutationError):
        adapter_for(provider, tokens, lambda _: pytest.fail("No provider POST")).send(
            draft.model_copy(update={"reply_context": context}), idempotency_key="stale-context-key"
        )
    assert tokens.calls == 0


@pytest.mark.parametrize("provider", MAIL_PROVIDERS)
@pytest.mark.parametrize("change", ["missing-binding", "different-binding", "rehashed-context"])
def test_reply_connection_epoch_must_match_draft_before_token_or_post(
    provider: IntegrationProvider, change: str
) -> None:
    draft = draft_for(provider)
    assert draft.reply_context is not None
    if change == "rehashed-context":
        context = draft.reply_context.model_copy(update={"connection_fingerprint": "c" * 64})
        context = context.model_copy(update={"fingerprint": reply_context_fingerprint(context)})
        draft = draft.model_copy(update={"reply_context": context})
    else:
        draft = draft.model_copy(
            update={
                "provider_binding_fingerprint": None if change == "missing-binding" else "c" * 64,
            }
        )
    tokens = Tokens()
    with pytest.raises(ProviderMutationError, match="source or account is unavailable"):
        adapter_for(provider, tokens, lambda _: pytest.fail("No provider POST")).send(
            draft, idempotency_key="mismatched-connection-key"
        )
    assert tokens.calls == 0


@pytest.mark.parametrize("provider", MAIL_PROVIDERS)
@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 415, 422, 429])
def test_reply_definite_rejection_never_retries_or_falls_back(
    provider: IntegrationProvider, status: int
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json={"error": "private provider detail"})

    with pytest.raises(ProviderMutationError) as error:
        adapter_for(provider, Tokens(), handler).send(
            draft_for(provider), idempotency_key="rejected-key"
        )
    assert not isinstance(error.value, ProviderSendUncertainError)
    assert "private" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("provider", MAIL_PROVIDERS)
@pytest.mark.parametrize(
    "failure", ["transport", "unexpected", "provider-error", "redirect", "server", "large-body"]
)
def test_postdispatch_failures_remain_uncertain_without_retry(
    provider: IntegrationProvider, failure: str
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if failure == "transport":
            raise httpx.ReadTimeout("private transport context")
        if failure == "unexpected":
            raise RuntimeError("private post-dispatch context")
        if failure == "provider-error":
            raise ProviderMutationError("private transport provider exception")
        if failure == "redirect":
            return httpx.Response(307, headers={"Location": "https://untrusted.invalid"})
        if failure == "server":
            return httpx.Response(503)
        return httpx.Response(
            200 if provider == IntegrationProvider.GMAIL else 202, content=b"a" * 65_537
        )

    with pytest.raises(ProviderSendUncertainError) as error:
        adapter_for(provider, Tokens(), handler).send(
            draft_for(provider), idempotency_key="uncertain-key"
        )
    assert "private" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("provider", MAIL_PROVIDERS)
def test_wire_size_rejection_precedes_token_resolution(
    provider: IntegrationProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("job_apply_pro.integrations.provider_clients.MAX_MAIL_WIRE_BYTES", 32)
    tokens = Tokens()
    with pytest.raises(MailAttachmentError):
        adapter_for(provider, tokens, lambda _: pytest.fail("No provider POST")).send(
            draft_for(provider), idempotency_key="oversized-key"
        )
    assert tokens.calls == 0


def test_gmail_bad_critical_headers_keep_correspondence_readable() -> None:
    headers = gmail_headers()
    headers.append({"name": "Message-ID", "value": "<duplicate@example.test>"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "gmail-1"}]})
        return httpx.Response(
            200,
            json={
                "id": "gmail-1",
                "threadId": "thread-1",
                "payload": {
                    "headers": headers,
                    "body": {"data": base64.urlsafe_b64encode(b"Readable correspondence").decode()},
                },
            },
        )

    message = adapter_for(IntegrationProvider.GMAIL, Tokens(), handler).list_messages()[0]
    assert message.reply_headers is None
    assert message.body_text == "Readable correspondence" and message.subject == "Original subject"


def test_graph_list_delta_pages_and_attachment_fetch_use_immutable_ids() -> None:
    requests: list[httpx.Request] = []
    delta = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert 'IdType="ImmutableId"' in request.headers["Prefer"]
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json={"value": [{"name": "public.pdf", "isInline": False}]})
        if "$select" in request.url.params:
            assert {"from", "sender", "replyTo", "internetMessageId"} <= set(
                request.url.params["$select"].split(",")
            )
        if request.url.path.endswith("/delta"):
            if "$skiptoken" not in request.url.params:
                return httpx.Response(
                    200, json={"value": [], "@odata.nextLink": delta + "?$skiptoken=page"}
                )
            return httpx.Response(
                200,
                json={"value": [graph_source()], "@odata.deltaLink": delta + "?$deltatoken=next"},
            )
        return httpx.Response(200, json={"value": [graph_source(hasAttachments=True)]})

    provider = adapter_for(IntegrationProvider.OUTLOOK, Tokens(), handler)
    assert provider.list_messages()[0].reply_headers is not None
    assert provider.sync_messages(cursor=None).messages[0].reply_headers is not None
    assert (
        provider.sync_messages(cursor=SecretStr(delta + "?$deltatoken=prior"))
        .messages[0]
        .reply_headers
        is not None
    )
    assert len(requests) == 6


def test_normalization_preserves_readable_data_when_reply_headers_are_unsupported() -> None:
    gmail = normalize_gmail_message(
        {
            "id": "gmail-1",
            "threadId": "thread-1",
            "from": "recruiter@example.test",
            "subject": "Original subject",
            "text": "Readable correspondence",
            "receivedAt": "2026-09-13T12:00:00Z",
            "headers": gmail_headers(**{"Message-ID": "bad"}),
        }
    )
    graph = normalize_outlook_message(graph_source(replyTo=[{}, {}]))
    assert gmail.reply_headers is None and graph.reply_headers is None
    assert gmail.body_text == graph.body_text == "Readable correspondence"
