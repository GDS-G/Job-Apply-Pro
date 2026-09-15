# ADR-0087: Reviewed Browser Upload Reconciliation

- Status: Accepted
- Date: 2026-09-15
- Build: Reviewed Browser Upload Reconciliation `v0.77.0-alpha.1`

## Context

The v0.67 Greenhouse form contract can upload one exact reviewed immutable document through a durable browser-effect attempt. If Playwright selects the file but its response is lost, the operation and attempt correctly become `UNCERTAIN` and cannot be retried. A visible same-stage filename may help close that local ambiguity, but a filename is not evidence that the provider received, retained, parsed, or associated the file with an application.

Generic upload reconciliation would be unsafe. A stale filename, duplicate filename, different form stage, changed origin, arbitrary file control, caller-supplied path, or old uncertain action must not acquire new authority. The staged plaintext should also exist for the shortest possible time.

## Decision

Before dispatch, only the exact elevated and confirmed Greenhouse `REVIEW_DOCUMENT_UPLOAD` action may prepare `BROWSER_UPLOAD_CONFIRMED` intent. The source must be a recognized non-confirmation stage with exactly one matching file control and locator; the action must have the exact locator-visible precondition, `NONE` verification, the approved upload intent, and a file directly inside that session's `staged-uploads` directory. Only `.doc`, `.docx`, and `.pdf` are admitted. The selected plaintext is hashed and measured before dispatch. Encrypted intent binds:

- operation, only attempt, external-effect request, action, control and locator;
- exact filename, SHA-256 and byte count;
- source origin, page type, Greenhouse stage, form-review fingerprint and page fingerprint; and
- the bounded source upload-status fingerprint, where the selected filename must be absent.

The persisted browser action always redacts `file_path`, and the staged plaintext is removed immediately after the action attempt returns or fails. Neither the renderer nor the reconciliation request supplies a path, filename, expected hash, page, stage, locator, result fingerprint, or claimed outcome.

After response loss, preview is available only while the exact session remains in `USER_TAKEOVER`, the operation and its only Playwright attempt remain `UNCERTAIN`, the unique redacted local action agrees with the encrypted intent, and a fresh read-only observation proves the same origin, page type and Greenhouse stage, a changed page fingerprint, and exactly one occurrence of the expected filename. Electron displays a Cancel-default native warning. Approval sends only operation/session identity, the immutable review fingerprint and `RECONCILE REVIEWED UPLOAD`, then repeats the complete proof.

Approval saves the fresh observation and checkpoint before terminalizing only the reconciliation row. The original operation and attempt remain `UNCERTAIN`. No upload, file staging, navigation, click, submit, worker restart or provider call is repeated. Forward-restore authentication recognizes exact field, navigation and upload payload schemas and fails closed on changed executable meaning; schema `20260915_0030` is reused.

## Consequences

A response-lost exact reviewed file selection can leave unresolved attention after two independent same-stage filename observations. The result means only that the local browser worker observed the exact filename after the uncertain selection. It does not prove provider receipt, file bytes, retention, parsing, malware scanning, application attachment, or submission.

Same fingerprints, absent or duplicate filenames, another stage or origin, changed review evidence, unsupported extensions, path-like filenames, invalid hashes/sizes, old or generic uploads, extra/missing attempts, unavailable workers, malformed observations and approval-time changes remain unresolved. Resume stays a separate deliberate action after a fresh capture. Live compatibility, production enablement and provider acceptance remain external gates.

## Validation

Automated coverage includes staged-byte hashing and cleanup, pre-dispatch encrypted intent, persisted-path redaction, response-loss success, same-fingerprint/absent/duplicate refusal, approval-time reproof, immutable uncertain history, authenticated API identity, client routing, strict IPC UUIDs, Cancel-default native review, renderer kind selection, and kind-specific restore authentication. Exact source, package and delivered-protocol evidence is recorded in the readiness audit for the final v0.77 checkpoint. Unsigned local evidence is not production acceptance.
