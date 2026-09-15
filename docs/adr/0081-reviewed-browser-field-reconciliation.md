# ADR-0081: Reviewed browser field reconciliation

- Status: Accepted
- Date: 2026-09-15
- Build: Reviewed Browser Field Reconciliation `v0.71.0-alpha.1`
- Schema: `20260915_0030`

## Context

The durable external-effect ledger correctly treats a missing browser-worker response as `UNCERTAIN` and prohibits automatic retry. That prevents duplicate typing or selection, but it also leaves a field action permanently unresolved when the original write actually succeeded and the user can still see the exact expected value in the unchanged page. A generic clear, retry, or operator override would weaken the v0.63 ownership boundary. Restart-time reconciliation also cannot depend on `browser_actions`: sensitive field values are deliberately redacted from that public history.

## Decision

Before dispatching an eligible field action, the browser runtime creates an encrypted reconciliation intent tied to the exact effect operation and attempt. Eligibility is restricted to `FILL`, `SELECT_LABEL`, `CHOOSE_CONTROLLED_OPTION`, `CHECK`, and `UNCHECK`, the fixed reviewed-field intended result, one exact locator, and deterministic `VALUE_EQUALS`, `SELECTED_LABEL_EQUALS`, or `CHECKED_EQUALS` verification. The encrypted payload contains the exact verification and request fingerprint; the public record exposes only whether reconciliation is available. The source page fingerprint, policy version, actor, and ownership identifiers remain queryable without exposing the answer.

Migration `20260915_0030` adds `external_effect_reconciliations`. `operation_id` is the primary key and foreign key to the durable operation; `attempt_id` is unique and references its exact attempt. An `AVAILABLE` row is immutable reconciliation authority, not proof of success. Only `reconcile_uncertain` may terminalize it as `CONFIRMED_APPLIED`, and only while the same latest attempt and operation remain `UNCERTAIN`. Terminal rows require an evidence reference, keyed evidence fingerprint, result-page fingerprint, and reconciliation timestamp. Destructive downgrade is refused while reconciliation history exists.

`BrowserWorker.verify_postcondition` is a read-only RPC. It validates the supplied `BrowserVerification`, allows only the three deterministic field verification kinds, invokes the existing verification logic, captures a new observation, and never invokes `_perform`. The browser runtime requires the session to remain in `USER_TAKEOVER`, the original allowed origin and page type to remain valid, the current page fingerprint to equal the source fingerprint, and the encrypted intent to match the durable operation, attempt, action kind, and request fingerprint. A false, unavailable, malformed, ambiguous, moved-page, stale-review, or legacy-without-intent result remains unresolved.

Preview calls prove the live postcondition and return only action kind, verification kind, page fingerprint, and a keyed review fingerprint. The Electron main process validates both UUIDs and shows a native warning whose default and cancel choice is **Cancel**. Approval sends the fixed phrase `RECONCILE VERIFIED FIELD` and exact preview fingerprint. The backend proves the postcondition a second time, persists the observation and workflow checkpoint, then records reconciliation evidence. It never repeats, types, selects, checks, clicks, navigates, uploads, or submits the original action.

The original external-effect operation and attempt remain immutable `UNCERTAIN` history. A terminal reconciliation excludes the effect from unresolved counts and attention lists while the public record retains reconciliation kind and time. The browser session remains `USER_TAKEOVER`; resuming automation is a separate explicit user decision.

Forward-restore inspection now protects 47 tables. Schema `20260913_0029` remains admissible only when empty and without the new table; recorded history must use the current schema. Encrypted reconciliation intents are authenticated and semantically checked during restore, including operation/attempt linkage, policy values, status-dependent evidence, and allowed action/verification kinds.

## Consequences

- One exact uncertain field write can be closed from visible deterministic evidence without repeating the external effect.
- Older uncertain effects, non-field actions, final submission, navigation, uploads, generic clicks, and effects without the pre-dispatch encrypted intent have no reconciliation authority.
- Sensitive expected values remain encrypted at rest and absent from public operations data, native dialogs, renderer state, diagnostics, and source control.
- Reconciliation is local proof of the current browser field state. It is not provider-side delivery proof and does not authorize another action.
- This release does not restart or navigate a browser to obtain reconciliation evidence. If the exact worker session is gone, the effect stays unresolved.
- Sanitized service, repository, API, IPC, renderer, restore, migration, and real Chromium read-only tests validate the bounded contract; they do not establish authorized live-provider compatibility.

## Alternatives rejected

- Retrying the uncertain action could duplicate or overwrite a successful write.
- Reconstructing expected values from redacted browser history cannot prove the original request.
- Letting the renderer supply a locator, verification, value, action kind, URL, or evidence would create new execution authority outside the durable ledger.
- Treating any matching field on a changed page as success would detach proof from the reviewed page.
- Changing the original `UNCERTAIN` result to `CONFIRMED` would erase material historical ambiguity.
- Automatically resuming the browser session after reconciliation would combine evidence closure with a separate automation decision.
