# ADR 0004: Local encryption and key boundaries

- Status: Accepted
- Date: 2026-08-05
- Build: Core `v0.2.0-alpha.1`

## Context

Candidate contact details, application answers, and resumable browser checkpoints can contain personally identifiable information. SQLite file permissions alone do not protect copied databases or backups.

## Decision

Protect sensitive JSON with AES-256-GCM using a new 96-bit nonce for every write. Store a versioned opaque envelope containing the key identifier, nonce, ciphertext, and authentication tag. Bind every envelope to record-specific additional authenticated data such as `candidate:{id}:contact` or `checkpoint:{workflow_id}:{sequence}`.

The application loads a base64-encoded 32-byte key from `JAP_MASTER_KEY` only when protected data is accessed. `KeyProvider` permits a future Windows Credential Manager adapter without changing domain or repository code. The initial environment provider is suitable for development; it is not a hosted secret-management system.

## Consequences

- Tampering and cross-record ciphertext substitution are detected.
- Database backups remain ciphertext-only and restore with the same key.
- Losing the key permanently loses access to protected records.
- Key rotation and Windows Credential Manager integration remain required before production readiness.
