# ADR 0043: Read-only required-field coverage review

## Status

Accepted for Required Field Coverage Review `v0.34.0-alpha.1`.

## Context

Exact observed controls, reviewed answer bindings, and verified one-field execution exist, but the operator otherwise has to compare those records manually before submission. A missing, stale, ambiguous, or manual-only required control must not be confused with a ready field. A diagnostic must also avoid becoming an implicit bulk-fill or submit authority.

## Decision

Add a read-only backend review bound to one supervised run and one application in the same workflow. It examines only the current snapshot's required controls and persisted binding, answer-revision, and execution metadata. It never resumes the browser, decrypts an answer, or executes an action.

Each required control receives exactly one classification:

- `READY_TO_EXECUTE`: while the run awaits the user, one current `AUTOFILL_ALLOWED` binding with its original answer revision and a deterministic executable locator exists; individual execution review is still required.
- `ALREADY_VERIFIED`: the ready binding also has a successful execution for the same answer revision and page fingerprint.
- `MANUAL_REQUIRED`: the control is unsupported, disabled, a legal attestation, or its approved permission requires user handling.
- `UNBOUND`: no binding exists for the current control key.
- `STALE_BINDING`: a binding exists but its page, portal, kind, answer, or answer revision is no longer current.
- `AMBIGUOUS_BINDING`: more than one current binding matches the control.

The response contains counts, bounded labels/reasons, binding IDs when unambiguous, and a SHA-256 review fingerprint over metadata. Optional controls are deliberately excluded. Cross-workflow requests fail closed.

## Consequences

The operator gains a deterministic checklist and can revisit individual binding or manual steps. The fingerprint is evidence of the review input, not authority to fill, submit, accept terms, or attest. The review is computed live and requires no migration or retention policy change.
