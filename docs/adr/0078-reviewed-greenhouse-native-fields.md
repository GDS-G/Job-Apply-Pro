# ADR-0078: Reviewed Greenhouse native fields

- Status: Accepted
- Date: 2026-09-15
- Build: Reviewed Greenhouse Native Fields `v0.68.0-alpha.1`

## Context

The existing supervised field executor can populate one exact reviewed field binding, and the v0.66 Greenhouse form contract can classify a native control as `REVIEW_FIELD`. Before this release those capabilities were intentionally separate. Composing them must not create bulk-fill authority, let a stale assessment authorize a changed page, or let custom widgets, legal attestations, signatures, uploads, navigation, or final submission enter through the ordinary-field path.

## Decision

Job Apply Pro composes Greenhouse `REVIEW_FIELD` controls with the existing generic one-field executor. The renderer passes only the supervised run identifier, approved binding identifier, current page fingerprint, and current Greenhouse form-review fingerprint. The approval schema forbids unrecognized fields, so a renderer or direct client cannot add a URL, locator, answer value, control metadata, action class, or confirmation phrase as authority.

For a Greenhouse run, the backend freshly observes and reassesses the page before decrypting an answer or dispatching a browser action. It requires the supplied form-review fingerprint to equal the current assessment and requires exactly one current contract entry whose control key matches the approved binding and whose action is `REVIEW_FIELD`. A missing, stale, duplicated, satisfied, unsafe, or differently classified control is rejected. Supplying a Greenhouse review fingerprint for another portal is also rejected.

The existing binding checks remain authoritative: workflow/application/run ownership, exact page fingerprint, answer revision and review status, portal, stable control key, semantic locator, kind, options, bounds, required state, and automation permission must all remain current. Main process validation presents a cancel-default native dialog and injects the fixed execution phrase only after approval. The executor performs exactly one elevated action and always returns control to the user. Answer plaintext is decrypted only immediately before execution, is marked sensitive at the browser boundary, and is excluded from durable action and execution evidence.

The Greenhouse form panel exposes `REVIEW_FIELD` controls as links into the existing observed-field-binding workspace. It shows an explicit manual handoff for `USER_INTERVENTION` controls: the user completes the visible portal control and captures the page again. No manual handoff is treated as completion, no value is inferred, and no automatic retry or form-wide fill is added. Document upload and one-stage navigation retain ADR-0077's separate action-specific reviews; final submission retains its separate default-off gate.

## Consequences

- One exact reviewed native field can be populated per cancel-default confirmation while remaining bound to both generic field review and current Greenhouse form review.
- Greenhouse gains no second browser executor; durable external-effect admission, postcondition verification, takeover, and ambiguity fencing remain shared.
- Custom widgets, legal/disclosure controls, signatures, repeated or unlocatable controls, uploads, navigation, login, MFA, CAPTCHA, assessments, and final submission receive no authority from this decision.
- Sanitized regressions establish source behavior only. Greenhouse remains `production_enabled=false`, its live-validated page-type list remains empty, and supervised execution remains disabled by default.
- Authorized live acceptance, additional named portals, package qualification, signing, and physical installed-app validation remain future gates.

## Alternatives rejected

- Automatically filling every control classified as native would combine independent approvals and amplify stale-page or partial-form risk.
- Trusting the renderer to classify the control or supply its value, locator, URL, or confirmation phrase would move authority across the least-trusted boundary.
- Treating a manual custom/legal handoff as satisfied without a fresh capture would create an unsupported completion claim.
- Adding a Greenhouse-specific field executor would duplicate safety logic and bypass the existing durable effect ledger.
