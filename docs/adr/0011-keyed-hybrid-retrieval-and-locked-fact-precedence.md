# ADR 0011: Keyed hybrid retrieval and locked-fact precedence

- Status: Accepted
- Date: 2026-08-05
- Build: Candidate Knowledge `v0.5.0-alpha.1`

## Context

Portal questions need fast retrieval across verified candidate facts and previously approved answers. A plaintext keyword index would leak sensitive information, while provider embeddings are not available until the AI Gateway milestone.

## Decision

Index only locked verified current claims and approved locked answer-library entries. Produce exact-match features as HMAC-SHA-256 blind token indexes and a deterministic 64-dimension keyed vector from the same normalized tokens. Rank results with 65 percent token-set overlap and 35 percent cosine similarity, filter profile and permitted use before decryption, and return evidence identifiers and provenance with every result.

Approved answers must cite locked verified claims from the same profile. Generated or extracted text has lower authority than a locked fact and cannot update it. The keyed vector is an offline privacy-preserving baseline, not a semantic embedding; a future AI Gateway may replace it behind the retrieval boundary while preserving authorization and provenance rules.

## Consequences

- The database cannot reveal candidate keywords or retrieval text without the local master key.
- Retrieval is deterministic, offline, testable, and usable before external model integration.
- Synonym and conceptual recall are intentionally limited until a governed embedding provider is available.
- Every reusable answer remains attributable to reviewed evidence.
