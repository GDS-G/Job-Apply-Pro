# ADR 0018: Encrypted operational recovery and entitlement boundary

- Status: Accepted
- Date: 2026-08-05
- Build: Dashboard, Backup & Licensing `v0.11.0-alpha.1`

## Context

Operational reporting must reconcile with durable evidence, backups must be recoverable without exposing candidate data, and commercial licensing must never lock a user out of their local recovery path. Replacing an active SQLite database from the live service would also create an unsafe split-brain process boundary.

## Decision

The backend derives dashboard totals and reports from persisted jobs, applications, workflow events, communications, model invocations, and portal runs. Submission attempts and independently confirmed submissions remain separate fields.

Local backups use consistent SQLite snapshots and already-encrypted candidate document files. A versioned ZIP manifest records application and schema versions, categories, paths, byte counts, and per-entry SHA-256 hashes. The complete archive is then authenticated and encrypted with the local AES-256-GCM key before an atomic write. Optional cloud providers may receive only this encrypted envelope and are disabled by default.

The live API can verify and stage a selective restore, but cannot apply it. Staging validates the outer archive hash, authenticated decryption, safe relative paths, entry sizes, and entry hashes, then produces a persisted fingerprint. Final application belongs to an offline launcher and requires the exact fingerprint and phrase `APPLY VERIFIED RESTORE`; database replacement preserves a pre-restore copy.

Commercial entitlement payloads use Ed25519 signatures and a device public-key field. Missing or invalid configuration fails closed for paid functions, and payment providers remain disabled by default. Every license state sets `recovery_allowed=true`; licensing cannot prevent backup listing, verification, staging, or offline application.

## Consequences

- Metrics can be audited against the evidence that produced them, including attempted-versus-confirmed submission distinctions.
- Tampered archives and path traversal fail before restore staging.
- Database application requires a future offline Electron recovery launcher; it is intentionally absent from the live API.
- Cloud backup transport, device enrollment, revocation, renewal, and payment checkout can be added behind stable interfaces without weakening local recovery.
