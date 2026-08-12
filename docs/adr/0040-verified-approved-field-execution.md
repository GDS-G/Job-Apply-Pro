# ADR-0040: Verified approved field execution

- Status: Accepted
- Date: 2026-08-12
- Build: Verified Approved Field Execution `v0.31.0-alpha.1`

## Context

Typed current controls and reviewed answer bindings existed, but the application did not execute them. A fill operation handles candidate data and can create a false or irreversible result if the page, answer, locator, constraints, or permission changed after review. The existing browser-action ledger also stored action and verification values, which would retain plaintext answers.

## Decision

Job Apply Pro may execute exactly one bound field only when the separate `JAP_SUPERVISED_FIELD_EXECUTION_ENABLED` policy is enabled and the desktop owner confirms the native dialog. The binding must be `AUTOFILL_ALLOWED`; the run must be `AWAITING_USER`; application workflow, portal, page fingerprint, control key, semantic kind, locator, constraints, answer identity, revision, status, and complete binding review fingerprint must still match a fresh browser observation.

Supported controls are native text, textarea, email, telephone, number, date, select, and checkbox controls. Radio groups, uploads, signatures, disclosures, legal attestations, disabled controls, custom widgets, and every final-submit action are prohibited. Select answers must identify exactly one current option. Checkbox answers must explicitly normalize to yes or no.

Execution uses an elevated, confirmed `BrowserAction` with semantic preconditions and post-action verification. The browser returns immediately to user takeover. An `application_field_executions` evidence row records non-secret identifiers, answer revision, before/after fingerprints, action kind, verification result, bounded error, and an action fingerprint derived only from metadata.

`BrowserAction.sensitive_value` causes the persistence repository to redact both the action value and verification value before writing browser history. Plaintext is decrypted only while constructing and sending the live action. It is never included in the execution evidence or its fingerprint.

## Consequences

- Execution fails closed on stale or ambiguous state.
- A failed browser verification is retained as failed evidence, never represented as success.
- Native UI confirmation and backend policy are independent gates.
- Radio/custom-widget execution requires a later explicit locator/option contract.
- Final submission remains governed by its separate exact-page confirmation flow.
