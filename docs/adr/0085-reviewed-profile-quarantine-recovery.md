# ADR-0085: Reviewed profile quarantine recovery

- Status: Accepted
- Date: 2026-09-15
- Build: Reviewed Profile Quarantine Recovery `v0.75.0-alpha.1`

## Context

ADR-0084 isolates a profile directory before destructive cleanup. If recursive cleanup fails, the canonical name remains absent and reuse remains blocked, but the isolated data is retained for manual support. A normal application restart needs a safe way to identify and finish that exact cleanup without exposing or accepting filesystem paths.

An isolated directory name alone is not authority to delete arbitrary data. Recovery must be restricted to the fixed engine root, a syntactically generated quarantine identity, exact durable profile history, a missing canonical profile directory, one unambiguous quarantine, and a freshly reviewed bounded inventory. Legacy anonymous `.retiring-<uuid>` directories created by v0.74 cannot be associated with one profile and remain manual-support items.

## Decision

Future retirement quarantine directories use `.retiring-<exact-profile-name>-<uuid>`. Profile names already use the restricted `[A-Za-z0-9_-]` alphabet, and the cleanup identifier is a canonical lowercase UUID. The public profile inventory exposes the opaque identifier only as `pending_cleanup_id`; it never exposes a path, filename inventory, cookie, token, credential, or content.

`BrowserProfileState.CLEANUP_PENDING` requires all of the following:

- one exact durable spelling and one exact historical origin set;
- no active session;
- the canonical profile directory is absent;
- the engine root and quarantine root are ordinary directories;
- exactly one syntactically valid quarantine is associated with that profile.

`preview_profile_cleanup` recomputes history and inventory under the process-wide profile lifecycle lock. Its review fingerprint binds the action kind, engine, exact profile name, cleanup UUID, origin set, every session identifier/state/update time, inventory digest, file and directory counts, and remaining bytes. Directory mtimes remain excluded; ordinary relative names, file sizes, file mtimes, and directory topology remain bound.

Electron accepts only engine, restricted profile name, and UUID from the renderer. Main requests the backend preview and displays a cancel-default native warning. Approval sends the immutable preview fingerprint and fixed phrase `REMOVE ISOLATED PROFILE DATA`. The backend repeats every check and removes only its derived quarantine. Durable browser sessions, effects, checkpoints, and historical name blocking remain.

If cleanup fails again and the quarantine still exists, the operation reports failure and remains reviewable. If the directory is absent after an exception, cleanup is treated as complete. Existing origin binding, retirement, and no-blind-retry rules are unchanged.

## Consequences

The owner can finish a failed local cleanup after restart without manual path handling. A quarantine that is duplicated, renamed, case-aliased, reparse-backed, changed after preview, paired with a restored canonical directory, or no longer tied to exact history fails closed.

This mechanism does not prove that arbitrary matching directories were originally created by Job Apply Pro against a hostile local administrator. Local administrator/kernel tampering remains outside the application trust boundary. It is not provider logout/revocation, forensic secure erasure, automated retention, or bulk cleanup. Anonymous v0.74 quarantines remain manual-support cases because their profile association was not recorded.

## Validation

Tests cover cleanup-pending discovery, retry after an injected recursive-removal failure, stale inventory rejection, exact route/body/UUID validation, authenticated API access, backend-client payloads, native cancel and approval behavior, and renderer status/action handling. Exact source checkpoint `18cc87691558bfe0509a5c0d48e1791b7ba99783` passes 1,903 backend tests at 86.67% coverage across 17,493 statements, 512 default desktop tests with two packaged-runtime opt-ins skipped, and every static/build/dependency-audit gate. Candidate checkpoint `783c6662071b5a8001d3e27f6b491362aaabb19b` passes both package smokes and the 2/2 delivered supervisor/recovery protocols; every executable independently reports `NotSigned`.
