# ADR-0089: Reviewed browser exact URL reconciliation

- Status: Accepted
- Date: 2026-09-15
- Build: Reviewed Browser Exact URL Reconciliation `v0.79.0-alpha.1`

## Context

ADR-0086 closes an interrupted reviewed Greenhouse stage click only when a fresh observation proves a recognized strictly later non-confirmation form stage. That provider-specific proof must remain narrow. The Reference ATS and future supervised adapters also perform direct `NAVIGATE` actions to an explicit allowlisted URL. When Playwright reaches that URL but its response is lost, the durable external-effect ledger correctly leaves the only attempt `UNCERTAIN`; however, the application previously had no action-specific way to close the resulting attention item without repeating the navigation.

Treating a partial path, URL substring, changed page, changed fingerprint, arbitrary link click, caller-supplied outcome, or manual browsing as proof would be unsafe. A click can carry form, JavaScript, download, or provider side effects that a resulting URL does not fully describe. Exact direct navigation therefore needs a distinct proof shape while continuing to use the navigation reconciliation lifecycle.

## Decision

`VerificationKind.URL_EQUALS` is the only direct-navigation postcondition eligible for this contract. The action must be one standard, non-sensitive `NAVIGATE` with an explicit HTTP(S) URL, no locator, coordinate, value, file, precondition, elevated permission, or confirmation state. Its verification value must equal the serialized action URL exactly. The current source URL must differ from the target, and both source and target origins must be valid and already governed by the browser session's origin allowlist before durable admission.

Before Playwright dispatch, the runtime writes an encrypted `BROWSER_NAVIGATION_CONFIRMED` intent bound to the exact operation and only attempt. The new payload shape contains:

- `action_kind = NAVIGATE`
- `navigation_scope = EXACT_URL`
- `postcondition = URL_EQUALS`
- the external-effect request fingerprint
- source origin, page type, and full source URL
- target origin and full target URL
- the existing reconciliation row's source page fingerprint, policy version, actor, operation, and attempt identities

The full URLs remain inside authenticated encrypted authority and evidence. The public preview exposes only `navigation_scope`, source/result page types, the result page fingerprint, and a keyed review fingerprint.

Preview performs a fresh read-only worker observation. It requires the exact target URL and target origin, a page fingerprint different from the admitted source, a bounded nonempty result page type, and worker-maintained `previous_action = NAVIGATE`. Approval supplies only the operation identifier, exact preview fingerprint, and existing fixed phrase `RECONCILE REVIEWED NAVIGATION`; the backend repeats the complete proof. A page change between preview and approval fails closed.

Successful approval saves the fresh observation and checkpoint and terminalizes only the reconciliation row. The original operation, Playwright attempt, and browser action remain immutable `UNCERTAIN` history. The session remains `USER_TAKEOVER`. No navigation, link click, retry, upload, field write, submission, worker restart, or provider request is performed by preview or approval.

The existing `browser-navigation-reconciliation-v1` policy and schema `20260915_0030` are reused because the new payload is an authenticated, disjoint alternative shape and does not reinterpret historical Greenhouse intents. Restore inspection accepts either the original Greenhouse-stage payload or this exact-URL payload and rejects mixed shapes. Restore policy closure also explicitly recognizes the v0.78 submission-reconciliation policy and requires changed-page evidence for terminal submission reconciliation.

## Consequences

- The Reference ATS now verifies direct navigation by exact URL rather than path containment.
- Operations uses the shared **Verify navigation outcome** action and a Cancel-default native warning. The warning distinguishes `GREENHOUSE_STAGE` from `EXACT_URL` after obtaining the backend preview.
- Arbitrary `CLICK` actions, link locators, `URL_CONTAINS`, redirects away from the exact target, target URLs already current at admission, missing worker action provenance, and older effects without pre-dispatch intent remain unresolved.
- Exact equality intentionally refuses otherwise-benign canonical redirects. Supporting those requires a separately reviewed redirect-chain or destination-identity contract.
- This release adds no production portal enablement and proves no live provider behavior, terms permission, authentication, delivery, installer signing, update, rollback, or physical Windows acceptance.

## Verification

Automated coverage includes exact pre-dispatch intent, worker-response loss, exact-target double observation, changed fingerprint, worker action provenance, inexact URL and stale-review refusal, no authority for `URL_CONTAINS`, no-op target refusal, authenticated restore acceptance/rejection, Reference ATS execution, API/shared-contract typing, native scope-specific copy, renderer gating, and historical Greenhouse navigation compatibility. Exact source checkpoint `5b7c59ea9a2c1bacc037ef953b2635ad44a53e17` passes 1,961 backend tests at 86.52% coverage across 18,091 statements and 526 default desktop tests with two explicit package-only opt-ins skipped. All static, production-build, dependency-audit and changed-content marker gates pass. Candidate checkpoint `0ec4bd1ef2189fca1f7aee2c2e1d63f74b1cd8d5` passes both packaged-backend smokes and both installer-delivered executable protocols. Exact artifact hashes and the unsigned state are recorded in the readiness audit. This does not satisfy protected, signed, physical, update/rollback, or authorized live-provider acceptance.
