# ADR-0075: Reviewed Greenhouse application launch

- Status: Accepted
- Date: 2026-09-14
- Build: Greenhouse Application Vertical Slice `v0.65.0-alpha.1`

## Context

Public Greenhouse discovery, exact-source review, evidence-backed qualification,
immutable resume selection, and generic supervised portal execution already
existed. They were not one safe vertical slice. The generic supervised start
accepted a renderer-supplied workflow, URL, and additional origins, so using it
for Greenhouse could bypass the reviewed job-readiness chain. A browser run also
did not retain which readiness bundle authorized its opening.

## Decision

Greenhouse starts use a dedicated reviewed launch contract:

1. `GreenhouseApplicationService.preview(application_id)` recomputes
   `JobReadinessService.snapshot`. It requires `READY`, a navigable saved public
   Greenhouse source, current requirements/qualification/selection reviews, and
   an HTTPS `greenhouse.io` subdomain.
2. The backend derives the workflow ID, source URL, exact origin, profile/job
   identity, immutable document version, and three review IDs. The renderer
   cannot supply those values.
3. `review_fingerprint` hashes that canonical bundle with policy
   `reviewed-greenhouse-application-launch/1`.
4. The Electron main process refetches the preview, compares the fingerprint,
   sanitizes untrusted display strings, and shows a cancel-default native
   confirmation. Only it adds `OPEN REVIEWED GREENHOUSE APPLICATION`.
5. `GreenhouseApplicationService.start` recomputes the preview again and starts
   the exact URL through `start_reviewed_greenhouse`. Generic supervised starts
   reject `GREENHOUSE`, and the desktop generic portal form excludes it.
6. The first durable `SupervisedPortalStepEvidence.before_fingerprint` is the
   reviewed launch fingerprint; `after_fingerprint` is the first observed page.
   This binds the saved portal run to the exact reviewed source/review/resume
   bundle without persisting raw candidate or posting content.

The existing gates remain authoritative: `supervised_portal_enabled` must be
true and `GREENHOUSE` must be explicitly allowlisted. Browser launch is visible,
headless mode is false, and control transfers to the user. Later field execution
still requires reviewed bindings and exact page fingerprints. Final submission
still requires its independent local policy gate, exact page fingerprint,
cancel-default native confirmation, exactly one recognized submit control, and
verified confirmation evidence.

## Rejected alternatives

- Trust the renderer's URL/workflow/origin fields: this can cross application
  boundaries and bypass readiness.
- Treat `READY` displayed earlier as continuing authority: source, evidence, or
  document changes can make it stale before launch.
- Auto-open immediately after resume selection: opening a real portal is a new
  user-visible external action and needs a separate preview and confirmation.
- Store raw source/review content in portal evidence: the canonical fingerprint
  supplies a durable binding without duplicating sensitive data.

## Consequences

Greenhouse now has a connected discovery-through-reviewed-browser path, but this
is not a live compatibility or production-release claim. Custom widgets,
Greenhouse-specific upload/navigation postconditions, authorized live testing,
legal/terms approval, signed packaging, and physical installed-Windows
acceptance remain open. Login, MFA, CAPTCHA, assessments, legal attestations,
signatures, and final submission continue to require user intervention or their
existing independent review gates.

## Verification

The v0.65 source checkpoint passes 1,820 backend tests at 86.79% coverage and
485 desktop tests with two explicit packaged-runtime opt-ins skipped. Ruff
lint/format passes 236 files; strict mypy passes 205 source/test/helper files.
Workspace Prettier, oxlint, TypeScript, contracts tests/type/lint/build, and the
Electron production build pass. Tests cover incomplete/stale readiness,
non-navigable or non-Greenhouse sources, wrong fingerprints/phrases, injected
renderer fields, generic-route bypass, native cancellation, late target
mismatch, exact derived command values, and durable first-step launch evidence.
