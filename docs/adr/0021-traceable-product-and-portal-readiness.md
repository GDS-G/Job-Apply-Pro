# ADR-0021: Traceable product and portal readiness

- Status: Accepted
- Build: Portal Readiness `v0.12.2-alpha.1`

## Context

The Phase 0–12 delivery sequence produced a secure, testable Windows alpha foundation, but the authoritative product document also contains long-term functional requirements that extend beyond those slices. Calling that foundation “source-complete” could be misread as proof that named live portals, provider OAuth, all document workflows, all target platforms, and release acceptance were finished.

The Phase 9 catalog also labeled each named portal replay validated after one sanitized search-page case. A search fingerprint alone does not prove job-detail recognition, application-form recognition, or fail-closed confirmation behavior.

## Decision

Maintain a versioned requirements traceability audit that distinguishes implemented and automated behavior, replay-only behavior, externally gated behavior, partial implementation, and roadmap-authorized deferral. Do not use phase completion as proof of full product completion.

Require every named Phase 9 portal replay profile to cover job search, job detail, application form, identifier-backed confirmation, and identifier-free confirmation rejection. Portal fingerprint rules use an explicit minimum confidence and default to complete required-signal coverage. The catalog may classify a page type only when one bounded rule is the unambiguous best match.

Expose replay-validated and live-validated page types separately. Replay evidence never changes `production_enabled`, authorizes credentials, permits legal attestations, or grants submission authority. Live validation is recorded only after provider-specific authorization, supervised evidence, and the relevant safety gates exist.

## Consequences

Readiness claims become narrower and auditable. A green replay suite proves the stated sanitized cases, not current live-site compatibility. Future releases have an explicit source-work queue instead of treating signing and provider accounts as the only remaining blockers. The extra portal fixtures and metrics increase maintenance work, but they provide a stable minimum regression boundary for every named target.
