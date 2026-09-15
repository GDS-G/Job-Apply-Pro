# ADR-0086: Reviewed Browser Navigation Reconciliation

- Status: Accepted
- Date: 2026-09-15
- Build: Reviewed Browser Navigation Reconciliation `v0.76.0-alpha.1`

## Context

The durable external-effect ledger correctly consumes a reviewed browser action before Playwright dispatch and marks an interrupted or unprovable result `UNCERTAIN`. Reviewed field writes gained a narrow read-only reconciliation path in v0.71. Reviewed Greenhouse stage navigation still required permanent manual handling even when the visible browser had clearly reached a recognized later form stage after the worker response was lost.

Treating any changed page as success would be unsafe. A changed page may be an error, an origin escape, the same form stage with dynamic content, or a final confirmation that belongs to the separate submission boundary. Reconciliation must also be prepared before dispatch; an old or generic uncertain click must never gain authority after the fact.

## Decision

An exact reviewed Greenhouse navigation action prepares a `BROWSER_NAVIGATION_CONFIRMED` reconciliation intent before `begin_dispatch`. The browser runtime admits this intent only when the action is one elevated, confirmed `CLICK` on the current contract's unique visible navigation locator, has the exact locator-visible precondition, uses no value/file/URL/coordinate authority, and the current Greenhouse form assessment is ready to advance. The encrypted intent binds the action kind, control key, semantic locator, source origin, source page type and stage, source form-review fingerprint, and external-effect request fingerprint. The existing reconciliation row and schema are reused; no migration is required.

An uncertain action remains immutable and places the session in `USER_TAKEOVER`. Preview performs one read-only browser observation and requires:

- the exact uncertain browser operation, its only Playwright attempt, unique local action row, and pre-dispatch navigation intent;
- the same allowed Greenhouse origin;
- a different page fingerprint;
- a recognized Greenhouse form page whose stage order is strictly later than the encrypted source stage; and
- a non-confirmation result, because final application confirmation remains under the separate submit contract.

The review fingerprint binds operation/attempt/session identity, action/control identity, request fingerprint, source and result page fingerprints/types/stages, origin, and policy version. Electron obtains the preview itself and displays a Cancel-default native warning. Approval sends only the operation identity, review fingerprint, and fixed phrase `RECONCILE REVIEWED NAVIGATION`. The backend repeats the proof, saves the new observation and checkpoint, then terminalizes only the reconciliation row. The original operation and attempt remain `UNCERTAIN`; no click, navigation, upload, or submit is repeated.

Available public external-effect records now expose their reconciliation kind so the renderer can choose the correct fixed review path. The renderer offers navigation reconciliation only for a matching browser session and `BROWSER_NAVIGATION_CONFIRMED`; it never selects the result page, stage, URL, locator, fingerprint, or evidence.

## Consequences

A response-lost reviewed Greenhouse stage transition can be safely removed from unresolved attention after independent current-page proof. Resume remains a separate deliberate action, and the supervised run must be freshly captured before further automation.

Same-page changes, earlier/equal stages, confirmation pages, another origin, unrecognized pages, changed review evidence, malformed/foreign operations, missing local evidence, and older generic clicks remain unresolved. Document upload, final submission, ordinary links, non-Greenhouse navigation, AI, mail, and calendar effects do not inherit this authority. Live compatibility and provider delivery are not established by synthetic fixtures.

## Validation

Automated tests cover pre-dispatch intent, response loss, recognized later-stage proof, same-page and confirmation refusal, approval-time reproof, durable immutable reconciliation, authenticated API route/body validation, backend-client routing, native Cancel/approve behavior, renderer kind-specific action selection, and existing field-reconciliation compatibility. Exact full source and package evidence is recorded only after the frozen candidate passes its release gates.
