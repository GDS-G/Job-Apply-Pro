# ADR 0016: Production-disabled portal catalog and replay contracts

- Status: Accepted
- Date: 2026-08-05
- Build: Portal Adapter Expansion `v0.9.0-alpha.1`

## Context

Phase 9 names eleven portal families, but enabling live automation before account-specific validation, terms review, drift monitoring, and controlled test plans would create unacceptable application and credential risk. The shared adapter contract is stable enough to implement generic workflows and regression evidence without claiming live readiness.

## Decision

Each named portal receives a typed catalog definition containing allowed domains, capabilities, execution strategy, page fingerprints, confirmation rules, limitations, version, and support status. Generic workflows identify only domain-bound pages with sufficient visible signals. Confirmation requires an approved page type, approved visible text, and a separate confirmation identifier.

Sanitized replay cases exercise every catalog definition and report per-portal accuracy and false-positive counts. Replays may contain page type, bounded visible text, control labels, and expected capability, but no credentials, cookies, candidate data, or live job records. Unsanitized cases are rejected.

Every Phase 9 entry remains `production_enabled=false`. Catalog and replay validation do not grant browser action authority. The loopback Reference ATS remains the only executable submission adapter.

## Consequences

- All roadmap-named portals have versioned generic-agent contracts and deterministic regression coverage.
- Desktop users can see replay status and production state without confusing the two.
- Live enablement requires a later accepted decision, supervised validation, monitoring, and per-portal safety review.
