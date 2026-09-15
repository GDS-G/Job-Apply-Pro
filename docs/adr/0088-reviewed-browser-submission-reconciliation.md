# ADR-0088: Reviewed Browser Submission Reconciliation

- Status: Accepted
- Date: 2026-09-15
- Build: Reviewed Browser Submission Reconciliation `v0.78.0-alpha.1`

## Context

The v0.69 Greenhouse final-submit contract permits one exact, native-confirmed click only after both default-off submission policy and the current provider form review agree. It records success only when the returned page is a recognized identifier-backed provider confirmation. If Playwright performs that click but its response is lost, the durable external-effect operation and only attempt correctly become `UNCERTAIN` and block retry. Before this release, a user who could visibly see the resulting confirmation page had no reviewed read-only path to close that local ambiguity.

Treating any thank-you page, changed URL, changed fingerprint, or caller-supplied identifier as proof would create false application records or duplicate-submission risk. Submission reconciliation therefore requires stronger evidence than field, navigation, or upload reconciliation and must be authorized before the irreversible action crosses the worker boundary.

## Decision

Before `begin_dispatch`, `BrowserRuntimeService.execute_action` prepares `BROWSER_SUBMISSION_CONFIRMED` only for the exact reviewed Greenhouse final-submit shape. The action must be one elevated and confirmed `CLICK` on the current `SUBMISSION_REVIEW` page's unique `FINAL_SUBMISSION_GATE`, with the exact semantic locator, one matching locator-visible precondition, `NONE` verification, no value/file/URL/coordinate authority, and the fixed intent `Submit the exact reviewed application`.

The encrypted intent binds:

- operation, only attempt, external-effect request, action, control, and semantic locator;
- exact source origin, page type, `REVIEW` stage, form-review fingerprint, and page fingerprint;
- portal kind `GREENHOUSE`, the compiled portal-adapter version, and postcondition `IDENTIFIER_BACKED_CONFIRMATION`.

An uncertain submission remains immutable and places the browser session in `USER_TAKEOVER`. Preview performs one read-only observation and accepts only the same exact Greenhouse origin with a changed page fingerprint, recognized `CONFIRMATION` form stage and catalog capability, required provider confirmation text, and one bounded identifier extracted by the shared portal confirmation policy. The raw identifier is not returned by the API, Electron bridge, or renderer; only a keyed fingerprint participates in the review evidence.

Electron obtains the preview itself and shows a Cancel-default native warning. Approval supplies only the operation identity, immutable review fingerprint, and `RECONCILE CONFIRMED SUBMISSION`. The backend repeats the complete read-only proof, saves the observation and checkpoint, and terminalizes only the reconciliation row. The original effect operation, Playwright attempt, and browser action stay `UNCERTAIN`; no click, submit, upload, navigation, field write, worker restart, or provider request is repeated.

After successful desktop approval, the renderer invokes the existing supervised current-page capture with the run's last durable fingerprint. That separate read-only classification advances the supervised run to `SUBMISSION_CONFIRMED` and stops the browser only if the identifier-backed page remains current. If the app closes or capture fails after durable reconciliation, the already-confirmed page can be captured later; reconciliation is not rolled back and no submit is replayed.

Forward-restore authentication recognizes the exact submission payload shape and Greenhouse HTTPS origin while reusing schema `20260915_0030`; no migration is required.

## Consequences

An exact response-lost reviewed Greenhouse submission can leave unresolved attention only after two independent identifier-backed confirmation observations. The normal desktop path then performs a third read-only supervised capture before changing the portal-run state. This is substantially stronger than filename, navigation, URL, or generic thank-you evidence.

Same fingerprints, missing or malformed identifiers, identifier text without the required provider confirmation signal, unrecognized page types, another origin, changed adapter meaning, stale previews, old/generic submit actions, multiple attempts, unavailable workers, malformed observations, and approval-time changes remain unresolved. Production Greenhouse remains disabled, and sanitized fixtures do not establish current live compatibility, account authorization, terms approval, provider retention, package signing, or physical Windows acceptance.

## Validation

Automated coverage includes exact pre-dispatch intent, response loss, identifier-backed success, stale/missing-signal/missing-identifier refusal, approval-time identifier reproof, immutable uncertain history, authenticated route/body identity, shared confirmation parsing, client/preload typing, strict IPC UUIDs, Cancel-default native review, renderer reconciliation followed by supervised capture, and kind-specific restore authentication. Exact full-suite and package checkpoints are recorded in the readiness audit; older evidence does not transfer.
