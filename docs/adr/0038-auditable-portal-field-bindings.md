# ADR 0038: Auditable portal field bindings

- Status: Accepted
- Date: 2026-08-12
- Build: Auditable Form Field Binding `v0.29.0-alpha.1`

## Context

Typed application answers are not sufficient to authorize form filling. A portal control can differ by widget type, option vocabulary, required state, limits, page version, and legal meaning. Binding a correct answer to the wrong control is an employment-impacting error.

## Decision

Persist an approved binding only after a preview combines the exact reviewed application-answer revision with a sanitized observed-field contract: portal, page fingerprint, stable control key, control kind, label, required state, options, numeric/date/character constraints, and legal-attestation flag.

The preview records canonical field, computed confidence/source, answer source/status/kind, validation rules, compatibility failures, proposed automation permission, and a SHA-256 review fingerprint. Approval recomputes the preview and requires the exact answer revision, fingerprint, permission, and confirmation phrase.

Only reviewed or promoted answers may bind. Type/control incompatibility, option mismatch, limit violation, stale state, and duplicate control binding fail closed. File uploads, signatures, disclosures, custom controls, and legal attestations never receive unattended autofill authority. Labels and options are encrypted at rest.

This release creates auditable metadata and review UI; it does not turn a binding into a browser action. Later execution must re-observe the page and prove that its fingerprint/control contract and answer revision still match the approved binding.

## Consequences

Mapping decisions become inspectable and testable without introducing live provider access. Dynamic layouts require a new preview after page or answer changes. The explicit review step adds friction intentionally; later releases may safely automate execution only from current approved bindings.
