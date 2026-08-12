# ADR-0035: Governed versioned answer library

- Status: Accepted
- Date: 2026-08-12
- Build: Governed Answer Library `v0.26.0-alpha.1`

## Context

Application portals repeatedly ask equivalent questions, but blindly reusing old text can propagate stale, unreviewed, or unsupported statements. The prior encrypted answer store had no correction history, optimistic concurrency control, or desktop management surface. Its current row and retrieval index could also be committed separately.

## Decision

An answer can enter reusable storage only after the exact `SAVE REVIEWED ANSWER` confirmation reaches the backend. The Electron boundary validates input and presents a native warning before sending that phrase. Evidence identifiers, when supplied, must reference locked, verified claims owned by the same candidate profile.

Every entry begins at revision 1. A reviewed correction supplies its expected revision; stale writes fail with conflict status. The current encrypted row, immutable encrypted revision, and reusable retrieval chunk are committed in one database transaction. Clearing either approval or lock removes the answer from retrieval in that same transaction. Corrections never mutate candidate claims.

Migration `20260812_0018` adds the current revision counter and `answer_library_revisions`, backfilling existing encrypted entries as revision 1 without decrypting them. Revision content retains the existing per-answer encryption contexts, so historical ciphertext remains decryptable only through the local key boundary.

## Consequences

- The desktop can create, correct, approve, lock, permission, evidence-link, and inspect history for reusable answers.
- Retrieval sees only the latest approved and locked revision.
- Historical answers remain auditable but cannot overwrite locked profile facts.
- Concurrent editors must refresh after another revision wins.
- This release does not automatically learn from model output or submit answers to live portals. Those remain separately governed future operations.
