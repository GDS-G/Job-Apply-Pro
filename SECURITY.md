# Security policy

Job Apply Pro handles high-sensitivity applicant, browser, email, and calendar data. Report suspected vulnerabilities privately to the repository owner rather than opening a public issue.

## Local protected data

Core and later builds encrypt candidate contacts, application answers, workflow checkpoint payloads, imported document bytes, extracted document layouts, and approved answer-library text with AES-256-GCM. The Workbench desktop generates `JAP_MASTER_KEY` and persists only an operating-system-protected blob through Electron `safeStorage`. Standalone backend developers must provide the key through a secure local environment method. Each ciphertext is authenticated against its record context, so moving a protected value to another record causes decryption to fail.

Never log decrypted values, encryption keys, session tokens, or full application form payloads. Backups may include versioned encrypted envelopes but must not include the master key in the same archive.

## Required controls

- Bind local services to loopback interfaces only.
- Authenticate every privileged desktop-to-backend operation with an ephemeral session token.
- Store secrets in an operating-system credential store; never in source or runtime logs.
- Encrypt sensitive profile fields, browser-state references, backups, and evidence artifacts.
- Keep Electron context isolation and renderer sandboxing enabled.
- Validate every IPC, API, model, browser, and provider payload at the boundary.
- Redact candidate data, credentials, tokens, and portal content from diagnostics.
- Treat portal text as data, never as executable instructions.
- Treat imported document text as untrusted data and keep extraction bounded by file, page, character, and block limits.
- Never let extracted or generated content overwrite a user-verified locked candidate fact.

## Candidate knowledge boundary

Candidate originals are stored only as authenticated ciphertext beneath the configured ignored runtime directory. Extracted text and approved answers are encrypted in the database. Retrieval indexes use key-derived blind token hashes and keyed numeric features instead of plaintext keywords or provider calls. Only locked, verified, current claims and approved locked answers are indexed; use restrictions are enforced before decryption.

Every extracted claim begins as `PROPOSED`. Verification is an explicit authenticated user action, conflicting locked canonical facts fail closed, and answer-library entries must cite locked verified claims from the same profile. Legacy `.doc` conversion is not performed inside the application because invoking a general office parser would expand the trusted execution surface.

## AI gateway boundary

All model traffic passes through the AI Gateway. Application services and agents must not instantiate provider SDKs or call model endpoints directly. External provider endpoints require HTTPS; local llama.cpp endpoints require loopback. API keys exist only in the secret-valued runtime configuration and are never returned by status/registry APIs, persisted in invocation records, cached with outputs, or written to logs.

Every request declares task type, prompt and schema versions, privacy classification, consent, source/profile versions, timeout, budget, retry/fallback policy, and cache behavior. External calls require explicit consent. Highly Sensitive and Restricted data are blocked from external providers; Routine and Employment Sensitive payloads receive field and identifier redaction where practical. Portal/user content is enclosed as untrusted data and cannot become system policy.

Structured responses and tool arguments are JSON-Schema validated. Tools must be declared by both the versioned prompt and request. Model output is not executable authority, cannot authorize submission, and cannot replace locked candidate facts. Cache values are context-bound ciphertext; cache keys and invocation logs contain hashes/version metadata rather than prompts or candidate plaintext.

## Browser runtime boundary

Browser automation runs in a separate Playwright process behind a constrained JSON-lines protocol. Every session has an explicit origin allowlist; while `production_automation_enabled` is false, only loopback fixture origins are accepted. Actions declare their target, preconditions, intended result, timeout, verification, retry limit, permission, and confirmation state. Elevated actions fail closed without confirmed approval.

Persistent user-data directories may contain authenticated cookies and storage. Keep them inside the configured ignored runtime directory, never inspect or export them through renderer IPC, never copy them into backups without encryption, and never include session tokens in observations or traces shared outside the workstation.

Imported document files remain encrypted at rest. For an approved upload, the browser service decrypts only the selected version into its session artifact directory, verifies the upload, and removes the plaintext staging directory immediately; stop cleanup repeats this deletion defensively.

## Portal submission boundary

The reference ATS adapter is deliberately restricted to `localhost`, `127.0.0.1`, and `::1`. Discovery responses and browser-observed job identity must agree. A run stops at `READY_TO_SUBMIT` with a persisted page fingerprint. Submission is an elevated action and proceeds only when the desktop supplies the exact fingerprint and explicit `SUBMIT REFERENCE APPLICATION` phrase. A click is recorded as `SUBMISSION_ATTEMPTED`; `SUBMISSION_CONFIRMED` requires a supported confirmation page and parsed confirmation code. Missing or changed evidence becomes `SUBMISSION_UNCERTAIN`, never confirmed.

The Portal Vertical Slice remains a development build. Real portal automation and application submission are intentionally not authorized.
