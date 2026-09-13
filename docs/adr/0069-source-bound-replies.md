# ADR-0069: Source-bound replies

## Status and scope

Accepted for Source-Bound Replies `v0.59.0-alpha.1`. This extends ADR-0065 with explicit new-message/reply modes, verified source provenance and stable account identity. It implements reviewed one-recipient replies, not automatic responses, reply-all, delivery/bounce reconciliation, remote draft synchronization or incoming attachment downloads. Live acceptance and signing remain separate gates.

## Account and connection identity

`integrations/oauth.py` captures Google's OpenID user-info `sub` or Microsoft's `/me` `id` during authorization. The mailbox address is a display/sender label, not stable identity. `OAuthTokenSet.account_identity` remains encrypted with tokens. Refresh preserves identity; it never backfills legacy credentials. Google uses existing allowlisted `openid`/`email` permissions and Microsoft existing `User.Read`; missing identity makes source-bound mail unavailable without expanding scopes.

`CommunicationService._mail_account()` derives `account_key` from provider plus stable identity. A separate connection fingerprint binds provider, credential reference and account hint. Refresh preserves this epoch; reconnecting creates a new credential reference and invalidates review even for the same address. UI labels and renderer input cannot establish identity. Legacy credentials require fresh authorization and source synchronization.

## Provenance and persistence

Only successful provider synchronization supplies trusted account/connection metadata to `_analyze()`. Public `/communications/analyze` can classify local input but cannot establish reply authority. Internal `NormalizedMessage.reply_headers` are excluded from public serialization. Incomplete reply metadata may leave readable correspondence without reply capability.

Migration `20260913_0026`, after `20260913_0025`, adds `source_account_key` and `source_connection_fingerprint`. Legacy values are 64 zeroes, never inferred from addresses. The unique correspondence key becomes `(provider, source_account_key, source_connection_fingerprint, provider_message_id)`, preventing cross-account/reconnect deduplication from reusing authority. Existing IDs, ciphertexts, drafts, audits and claims remain intact. Downgrade refuses account-bound correspondence; development downgrade is not operational recovery. Backup schema revision advances to `20260913_0026`.

`MailReplyContext`, version `mail-reply-v1`, contains provider, stable account key/label, connection fingerprint, source record/message/thread IDs, ID format, exact recipient/subject, RFC message ID, references, MIME-reply support and canonical fingerprint. It is encrypted within records and drafts. Public record projection exposes validated review context only for the current connection; stale legacy authority is withheld, not repaired.

## Strict contracts and headers

`MailMode` distinguishes `NEW_MESSAGE` and `REPLY`. Reply creation requires source analysis ID, source fingerprint and reviewed body/optional versions. Provider/recipient/subject overrides are forbidden, including explicit null. New messages require explicit provider/recipient/subject and forbid source fingerprint, reply context and provider thread. A failed reply never silently becomes unthreaded mail.

`domain/mail_threading.py` owns mailbox, identifier, header and context validation. Addresses are one plain ASCII dot-atom mailbox. Lists, display-name overrides, controls, Unicode formatting and header injection are rejected. Provider IDs are bounded to 500 characters without whitespace; exact subjects to 1,000 characters; headers to 200 entries; references to 50 IDs/8,192 characters. RFC message IDs are validated before MIME serialization. Critical duplicate Gmail headers and ambiguous sender/reply metadata fail closed. Empty source subjects are valid replies; new subjects must be nonempty. The app does not prepend Re: or rewrite the source subject.

`create_draft()` fingerprints mode, account/connection/source context, recipient, subject, body and ordered attachments. ADR-0065 ownership, encrypted-byte and PDF/DOCX container checks remain: at most four versions totaling 2 MiB. No arbitrary file path, remote fetch, CC/BCC or reply-all is added.

## Offline preview and dispatch

An explicit new message may be saved offline without a verified account. Its account key/label remain null, reply context absent and thread empty. It is visibly not send-ready. Connecting later never binds that preview; create and review a fresh draft. Replies always require verified synchronized source authority.

`send()` checks idempotency replay against exact draft/fingerprint. Fresh legacy/offline/unbound attempts are rejected before claiming or provider access. Current identity, connection epoch, source context and draft fingerprint are rechecked. An atomic per-draft claim precedes dispatch; attachments and bytes are checked again. Different idempotency keys cannot bypass previous attempts. Uncertainty retains the claim without automatic resend.

`_validated_mail_context()` repeats mode/account/recipient/subject/source checks at the wire boundary. `_mime_message()` serializes validated headers with an SMTP policy preserving literal message-ID tokens. Proven pre-dispatch failures remain distinct from uncertain requests. A gone reply source is a rejection, never a new-message fallback.

## Provider wire contracts

Gmail sends one base64url MIME payload. Replies include exact source threadId, In-Reply-To, validated accumulated References and matching subject; new messages omit threading. Success requires HTTP 200 and a message ID. This implements [Google's documented threading contract](https://developers.google.com/workspace/gmail/api/guides/threads); fixtures prove serialization, not eventual mailbox placement.

Outlook reads, delta sync and sends request `Prefer: IdType="ImmutableId"`; IDs preserve case and are encoded as one path segment. Replies use one `POST /me/messages/{source_message_id}/reply`. Text-only replies send reviewed recipient/subject/body as JSON. Attachment replies use base64 MIME only when source Sender, From and effective Reply-To agree; otherwise they fail closed before dispatch. There is no remote create-draft/attach/send sequence or new scope. See [Microsoft's reply contract](https://learn.microsoft.com/en-us/graph/api/message-reply?view=graph-rest-1.0) and [immutable-ID guide](https://learn.microsoft.com/en-us/graph/outlook-immutable-id).

`_mail_post()` bounds encoded requests to 4 MiB and accepted responses to 65,536 bytes, disables redirects and authorizes before dispatch. Explicit 400/401/403/413/415/422/429 responses, plus reply 404, are definite rejections only after response cleanup completes. Unexpected status, transport/cleanup exceptions and malformed acceptance are uncertain. Outlook requires 202 and returns no message ID. Acceptance is not delivery or thread-placement proof.

## API, IPC and UI

Authenticated routes create/list/read immutable local drafts and send a selected draft with fingerprint/idempotency key. `mail-draft-ipc.ts` validates exact typed objects, retrieves authoritative draft state before and after native confirmation, and displays mode, account, source, recipient, subject, body and manifest. Cancel is default. Tokens and decrypted attachment bytes never reach the renderer.

The reviewed-mail panel separates modes, shows account/source availability and invalidates review when mode, source, workflow, documents or backend state changes. Generation guards prevent delayed reads replacing current selection. Proven pre-dispatch review failures require successful explicit refresh before manual review; uncertainty remains retained. Legacy or unavailable source authority never silently becomes new mail.

## Validation and remaining work

Tests cover identity/reconnect isolation, refresh, missing identity, forged analysis, legacy migration/downgrade refusal, strict headers, empty reply subjects, exact wire formats, immutable IDs, ambiguous routing, gone sources, uncertain responses, concurrent claims, encrypted storage and native stale-review rejection. Exact integrated and artifact evidence belongs in the readiness audit.

The packaged offline probe verifies two immutable encrypted new-message previews, repeated pre-claim refusal with zero mutation audits, exact preservation through backup/restore and continued refusal afterward. It does not fabricate authorized provider identity. Accepted/uncertain send-history restore preservation remains source-tested, not exercised by this offline package probe. Authorized registrations/sync, native-window acceptance, delivery reconciliation, recruiter-first attachment profile selection and broader incoming attachments remain separate work.

