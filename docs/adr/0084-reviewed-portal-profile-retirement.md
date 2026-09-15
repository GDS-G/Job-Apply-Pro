# ADR-0084: Reviewed portal profile retirement

- Status: Accepted
- Date: 2026-09-15
- Build: Reviewed Portal Profile Retirement `v0.74.0-alpha.1`
- Storage schema: unchanged at `20260915_0030`

## Context

ADR-0083 binds each persistent browser profile to one engine, exact case-preserved name, and exact origin set. Those profiles can retain browser-managed cookies and local sign-in state. The product therefore needs a deliberate way to remove one profile's local browser data without deleting durable session evidence, accepting a renderer-supplied path, or turning retirement into silent profile reuse.

Deleting session rows would destroy audit history and could break external-effect, checkpoint, supervised-run, and restore relationships. Treating a missing directory as a fresh profile would silently recreate a retired cookie jar identity. A renderer-only delete would bypass current backend state and native confirmation.

## Decision

The backend derives browser-profile inventory from all durable session history, grouped by engine and case-insensitive profile name. It exposes `AVAILABLE`, `ACTIVE`, `RETIRED`, or `INCONSISTENT` state without returning a filesystem path or browser data.

Retirement is a two-step backend review:

1. `preview_profile_retirement` requires exact historical spelling, one exact origin history, no `STARTING`, `ACTIVE`, or `USER_TAKEOVER` session, a present ordinary engine/profile directory, and a bounded filesystem inventory containing no symlink, junction, reparse point, or unsupported entry. The review fingerprint binds the action, engine, exact name, origins, all session identifiers/states/update times, inventory fingerprint, counts, and bytes.
2. The Electron main process receives that authenticated preview, displays a cancel-default native warning with the exact engine, origins, retained-session count, file/directory counts, byte count, and review fingerprint, and can submit only the immutable preview with the fixed confirmation phrase.
3. `retire_profile` recomputes the preview, rejects a stale fingerprint, rechecks the engine root, atomically renames only the derived profile directory to a generated sibling quarantine name, re-inventories it, and removes the quarantine tree only if its inventory is unchanged. The renderer supplies no path, deletion status, counts, or fingerprint.

A typed process-wide reentrant lifecycle lock serializes create, list, preview, retire, takeover, resume, restart, and stop operations across request-scoped service instances. This prevents a session activation or restart from racing retirement.

Durable session records remain unchanged. Once the directory is absent, profile inventory reports `RETIRED`, and `create_session` rejects the historical name as retired/removed/unsafe. A new profile name is required. No database migration is needed because the durable history plus canonical directory absence is the tombstone.

## Security and failure boundaries

- Engine and profile paths are derived only from the configured resolved browser-data root, a `BrowserEngine` enum, and the existing ASCII profile-name grammar.
- The engine root and every inventoried entry must be ordinary storage. Root/nested reparse points and unsupported entries fail closed for manual review.
- Inventory is capped at 200,000 entries. The preview exposes counts and bytes, never filenames, cookie contents, credentials, tokens, or filesystem paths.
- The native dialog defaults and cancels to no change. A stale review causes no rename or deletion.
- The atomic rename removes the canonical identity before recursive cleanup. If cleanup fails after isolation, the original name remains absent and reuse stays blocked; the quarantine is preserved for manual review.
- `shutil.rmtree` runs only on the generated, re-inventoried quarantine sibling. Python 3.12 Windows behavior does not traverse directory junction contents, and the preceding reparse checks narrow the remaining race boundary.
- This feature is not secure erasure of storage media, provider logout/revocation, or deletion of server-side sessions. Users should revoke provider sessions separately when required.

## Consequences

- Users can deliberately remove one stopped profile's local cookies and browser state without deleting application audit history.
- Retired and inconsistent profiles are not offered for reuse. Active profiles cannot be retired.
- Manual deletion of a known profile directory is interpreted conservatively as retirement, so the historical name cannot silently recreate storage.
- Quarantine cleanup failures require manual support handling and never authorize reuse.
- Secure media erasure, automatic provider logout, retention policy, and administrative bulk cleanup remain separate future work.

## Alternatives rejected

- Deleting browser-session rows would destroy governed evidence and restore relationships.
- Accepting a renderer-supplied path would create a destructive path-confusion boundary.
- Removing data immediately from the renderer would omit fresh state validation and native consent.
- Reusing the same historical name after deletion would make retirement indistinguishable from accidental local-data loss.
- Storing a new database tombstone would add schema and restore-policy complexity when immutable history plus directory absence already provides a fail-closed state.
