# ADR-0065: Verified mail attachments

## Status and reproduced defects

Accepted for Verified Mail Attachments `v0.55.0-alpha.1`, subject to final integrated and packaged validation. Previously, approved drafts fingerprinted `document_version_ids` but Gmail and Outlook transports omitted their content. A message could be reported confirmed while selected attachments were never sent. Outlook also created a draft through an endpoint requiring `Mail.ReadWrite`, although the application permits `Mail.Read` and `Mail.Send`. Neither defect can be fixed solely by supplying account credentials.

## Immutable review manifest and bytes

`MailAttachmentResolver.resolve()` requires an owning application workflow and resolves selected versions through the knowledge/workbench repositories. Every document must belong to the workflow's candidate profile, remain unarchived, and have a supported kind: resume, cover letter, certification, education or portfolio. `OTHER` is not supported in this initial policy. Recruiter-first attachment correspondence without a workflow remains a documented limitation, not an inferred profile association.

The resolver confines the resolved storage path to configured document storage, opens a regular file, bounds ciphertext before reading, authenticates decryption with the existing `document:<version-id>:file` context, and compares actual SHA-256 with the stored version. `VerifiedMailAttachment` is a frozen internal metadata/bytes pair; bytes are excluded from its representation. No plaintext staging file, renderer payload or audit field contains attachment bytes. Resolved-path checking is not a race-proof OS file-handle sandbox against a local actor modifying paths concurrently.

`MailAttachmentManifest` uses policy version `mail-attachments-v1`, profile ID and an ordered tuple of `MailAttachmentMetadata` records: document/version IDs, filename, MIME, SHA-256 and actual byte length. It is persisted inside the existing authenticated encrypted draft payload. `_mail_draft_fingerprint()` binds this manifest, ordered selection, workflow, correspondence, recipient, subject, body, provider connection, category and review policy. Send resolves bytes again and requires the new manifest to equal the reviewed manifest. Legacy attachment drafts without a manifest and all legacy drafts without a provider-binding fingerprint, including text-only drafts, cannot be sent; create and review a new draft instead.

## Bounded attachment policy

`MAX_MAIL_ATTACHMENTS` is four unique versions. `MAX_MAIL_ATTACHMENT_BYTES` is 2 MiB combined raw content. `MAX_MAIL_WIRE_BYTES` is 4 MiB encoded request content. `MAIL_MEDIA_TYPES` maps `.pdf` to `application/pdf` and `.docx` to the standard Word Open XML MIME type. Filenames are limited to 200 characters and reject control characters, path separators, colon and surrounding whitespace. Extension, MIME, actual length and reviewed hash must agree.

`validate_attachment_bytes()` requires the PDF header and opens the container using the existing PDFium dependency with a 1–100 page limit. DOCX validation bounds central-directory entries to 2,000, expanded total to 32 MiB and each member to 8 MiB; rejects encrypted members, unsupported compression, duplicate/case-colliding or path-shaped names and macro markers; reads bounded members to check lengths/CRC; and validates required content-type/document XML using `_validate_docx_xml()`. DTD/entity declarations and macro-enabled main content are rejected. `validate_mail_bundle()` checks exact ordered metadata/selection equality and aggregate limits before transport access.

These checks establish supported container/type and reviewed-byte integrity, not full rendering, malware detection, active-content removal, metadata stripping or semantic suitability. The exact original PDF/DOCX is sent; embedded metadata and visible personal information remain. Parser work is bounded by file/container limits, not a separate process-wide memory quota or hard cancellation guarantee. Large attachments and upload-session lifecycles are not implemented by this policy.

## Provider dispatch and honest outcomes

Gmail constructs an SMTP-policy multipart `EmailMessage` containing the reviewed text and exact attachment bytes, then base64url-encodes it in the `messages/send` JSON request. A valid bounded message identifier is retained only when returned by a successful response. The reviewed thread ID is included, but RFC In-Reply-To/References headers are not yet supplied; verified provider reply-thread association is not guaranteed. See the [official Gmail sending guide](https://developers.google.com/workspace/gmail/api/guides/sending).

Outlook uses one `POST /me/sendMail` request with inline `fileAttachment` JSON under existing `Mail.Send`; it no longer creates a remote draft or requires `Mail.ReadWrite`. A `202` response has no message identifier and establishes provider acceptance, not recipient delivery. No identifier is fabricated. See [Microsoft sendMail](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0) and the contrasting [create-message permissions](https://learn.microsoft.com/en-us/graph/api/user-post-messages?view=graph-rest-1.0). Outlook conversation threading is not guaranteed by sending a new message with the reviewed subject; do not describe the local thread association as a verified provider reply relationship.

`_mail_post()` validates encoded size before token/network access, disables redirects, and bounds response content to 65,536 bytes. Explicit supported rejection responses become failed attempts. Uncertain transport, unexpected status, invalid/missing success evidence or unhandled post-reservation failures become `UNCERTAIN`; they are not silently retried. `ProviderMailResult` carries an optional provider resource ID only. New successful mail audits are `ACCEPTED`, not `CONFIRMED`. Historic audit outcomes are not rewritten as newly verified delivery.

`BoundMailTokenProvider` binds the invocation to its reviewed provider and opaque OAuth connection reference. `OAuthConnectionService.access_token_bound()` refuses another connection. Refresh preserves the reference and stores refreshed tokens only if that reference is still current, so a concurrent reconnect cannot be overwritten. Tokens, references and provider-binding hashes are not renderer-visible draft metadata.

## Durable send admission

Migration `20260913_0024` adds `mail_send_claims`, with one primary-key claim per draft and one unique audit reference. `CommunicationRepository.claim_mail_send()` commits a `PLANNED` audit and its claim together before provider dispatch. Concurrent calls cannot claim the same immutable draft twice. Existing mail audits also prevent legacy resend even without a new claim row. Integrity conflicts roll back and return the winning attempt for strict resource/key/fingerprint validation.

`send_draft()` preserves exact-key replay and rejects a different draft, fingerprint or idempotency binding. `add_audit()` cannot overwrite another resource or mutation kind through a reused key. A crash after reservation leaves a recorded unconfirmed attempt; a new key does not authorize another send of the same draft. Local reservation does not prove provider exactly-once delivery, and an idempotency header is not an external deduplication guarantee. After a failure, inspect the recorded outcome before explicitly preparing a new draft; never recreate drafts automatically to bypass uncertainty.

## Desktop review boundary

`MailDraftPanel` exposes draft creation, exact selected versions, manifest details and audit outcomes. `mail-draft-ipc.ts` validates allowlisted inputs, allows only review-required drafts, fetches the backend's current draft for approval, validates its ordered manifest, and uses a native confirmation dialog. Untrusted strings are quoted and directional controls are visibly escaped so they cannot masquerade as approval instructions. The main process owns the confirmation identity and idempotency key; the renderer cannot manufacture these privileged values. Plaintext attachment content never crosses the bridge. Provider acceptance and uncertainty are labeled distinctly from delivery.

## Validation and remaining work

Tests cover owner/version/hash/path/size/type failures, encrypted storage and legacy manifests, exact Gmail/Outlook wire bytes, no-token/no-network preflight rejection, account reconnection, atomic concurrent claims, cross-kind idempotency collisions, uncertain outcomes, migration/restore compatibility, desktop validation and native confirmation. Final counts, runtime source commit, packaged smoke, artifact hashes and protected CI belong in the readiness audit.

No live mail is sent by development validation. OAuth registrations/scopes, provider terms and sanitized authorized acceptance remain necessary. General incoming-attachment download, large-file sessions, arbitrary document categories, recruiter-first profile selection, verified Outlook threading and delivery/bounce reconciliation remain separate capabilities.
