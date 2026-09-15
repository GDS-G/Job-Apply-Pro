# ADR-0079: Reviewed Greenhouse final submission

- Status: Accepted
- Date: 2026-09-15
- Build: Reviewed Greenhouse Final Submission `v0.69.0-alpha.1`

## Context

The supervised portal service already contains a separate default-off final-submit gate and identifier-backed confirmation classifier. The Greenhouse form contract separately classifies submit controls as `FINAL_SUBMISSION_GATE`, but before this release the generic submit call did not require that current provider review. Greenhouse submission must not inherit navigation, field, upload, or renderer authority, and a click alone must never establish success.

## Decision

Job Apply Pro composes the existing final-submit service with the current Greenhouse form contract. The renderer passes the supervised run id, current page fingerprint, and current Greenhouse form-review fingerprint. The approval model forbids unrecognized fields. Electron main validates the optional fingerprint, presents the existing cancel-default native warning with the provider-specific boundary, and injects `SUBMIT APPLICATION` only after approval.

The backend retains both global policy gates: supervised portal execution and final submission must be explicitly enabled, and Greenhouse must be in the local allowlist. The run must already be `READY_TO_SUBMIT`, the page fingerprint and fixed phrase must remain exact, and a fresh browser observation must remain on the allowed origin. For Greenhouse, the backend freshly reassesses that observation, requires the exact form-review fingerprint, requires the `REVIEW` stage, and requires exactly one `FINAL_SUBMISSION_GATE`. The corresponding observed control must be unique and semantically locatable. Busy, inert, accessibility-hidden, repeated, unlocatable, disabled, absent, or ambiguous submit controls receive no contract authority.

The one elevated confirmed click uses the exact observed semantic locator and a visible-locator precondition. It continues through the durable browser external-effect ledger, so a consumed, failed, or ambiguous attempt is not blindly retried. Success requires the existing portal catalog to recognize a Greenhouse confirmation page on the allowed provider domain, match the required confirmation signal, and extract an identifier. A verified click without that identifier-backed confirmation becomes `SUBMISSION_UNCERTAIN`, returns control to the user, and makes no success claim.

Non-Greenhouse final submission behavior remains on the existing path and rejects injected Greenhouse form authority. Fields, uploads, navigation, manual controls, and final submission remain separate permissions and reviews.

## Consequences

- The sanitized Greenhouse vertical slice can proceed from reviewed form state through one exact final-submit action to identifier-backed confirmation without trusting renderer-provided URL, locator, control, action, or confirmation evidence.
- Final submission remains globally default-off, provider allowlisted, cancel-default, one-attempt, and live-unvalidated.
- Multiple or unsafe submit controls fail before action even if the generic page classifier recognizes a submission-review page.
- Missing confirmation identifiers, changed pages, origin escapes, failed browser results, or unrecognized confirmation pages remain uncertain and require user review; none authorizes automatic retry.
- Authorized live acceptance, package qualification, protected CI/security, signing, a second signed version, and physical installed-app validation remain external gates.

## Alternatives rejected

- Reusing ready-stage navigation for the submit button would collapse a materially irreversible action into a lower-risk permission.
- Treating the renderer's control key, URL, locator, or confirmation message as authority would cross the least-trusted boundary.
- Treating a successful click or generic thank-you text as confirmation would permit false submission claims.
- Automatically retrying an uncertain final-submit result could create a duplicate external effect.
