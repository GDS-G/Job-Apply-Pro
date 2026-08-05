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

## Browser runtime boundary

Browser automation runs in a separate Playwright process behind a constrained JSON-lines protocol. Every session has an explicit origin allowlist; while `production_automation_enabled` is false, only loopback fixture origins are accepted. Actions declare their target, preconditions, intended result, timeout, verification, retry limit, permission, and confirmation state. Elevated actions fail closed without confirmed approval.

Persistent user-data directories may contain authenticated cookies and storage. Keep them inside the configured ignored runtime directory, never inspect or export them through renderer IPC, never copy them into backups without encryption, and never include session tokens in observations or traces shared outside the workstation.

The Browser Runtime alpha remains a development build. Real portal automation and application submission are intentionally not authorized.
