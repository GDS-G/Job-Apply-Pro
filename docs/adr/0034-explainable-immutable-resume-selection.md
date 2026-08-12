# ADR-0034: Explainable immutable resume selection

- Status: Accepted
- Date: 2026-08-12
- Build: Explainable Resume Selection `v0.25.0-alpha.1`

## Context

Candidate profiles can hold multiple resume variants, while each application stores a specific document-version reference. The product requirements call for choosing a resume according to the target job, technologies, seniority, industry, and user rules. A silent automatic choice would hide consequential employment logic, and selecting a mutable document record would weaken submitted-document evidence.

## Decision

Rank the latest immutable version of each eligible, active resume using a versioned deterministic policy. The score combines required-requirement coverage (35%), all-requirement coverage (25%), job-title token overlap (20%), the strongest job-family/operator-tag overlap (10%), and an optional primary-resume preference (10%). Seniority and industry participate when present in the title, requirements, or operator-maintained tags. Stable ordering uses score, normalized variant label, then document ID.

Return every candidate, score, matched requirement IDs, matched tags, and plain-language reasons. A requirement counts as matched only when all of its significant normalized tokens occur in the document evidence; this intentionally prefers conservative under-matching over a misleading partial match. The top result is a recommendation, not an automatic decision. An operator may select any reviewed result after a native confirmation. Approval recomputes the recommendation and requires a fingerprint bound to the application, current selection, current job and requirements, candidate immutable versions, scores, exclusions, and preferences.

Persist the selected document-version ID and an append-only audit in one database transaction. The audit retains the score, criteria, reasons, and review fingerprint. Import metadata is explicit in the desktop so variant labels, job-family tags, and the primary flag are controlled by the operator.

## Consequences

- Selection is explainable, reproducible, locally computed, and independent of provider credentials or external AI.
- Changes to job requirements, documents, exclusions, or preferences invalidate approval and require another preview.
- The recommendation is only as complete as extracted text and operator-maintained metadata. It does not infer protected traits, fabricate experience, or prove candidate eligibility.
- Weight changes are product-policy changes and require tests, documentation, and a new release record.
