# ADR-0082: Interrupted forward restore resume

- Status: Accepted
- Date: 2026-09-15
- Build: Interrupted Forward Restore Resume `v0.72.0-alpha.1`
- Storage schema: unchanged at `20260915_0030`
- Recovery record format: compatible extension of `interrupted-restore-rollback/2`

## Context

ADR-0071 retains authenticated encrypted before- and after-images for every target before publishing the restore guard. It can converge an interrupted operation to the exact sealed `BEFORE` state, but it cannot complete the already reviewed `AFTER` plan. A user who still wants the reviewed restore must therefore roll back, reopen the application, restage from external files, and start another operation even though the active operation already owns a complete authenticated postimage inventory.

Automatically choosing forward completion would be unsafe. The current target set may contain a mixture of exact before and after images, and rollback is also a valid recovery choice. The recovery-only app must not reread staging paths, query SQLite, merge later activity, invent a target state, or let a previously published decision change direction.

## Decision

The v2 decision record keeps its existing encrypted `decision.v2.enc` name and policy context, but its authenticated action is now either `ROLLBACK` or `RESUME`. Existing rollback records remain valid. A resume decision uses a distinct SHA-256 review fingerprint over the fixed policy, `RESUME`, and the canonical prepared-intent digest; it cannot collide with or substitute for the rollback fingerprint.

`RestoreRollback.inspect()` authenticates the prepared intent, every retained before/after image, every current target, any decision, and any receipt. A receipt-free `INTERRUPTED` operation exposes both exact choices. Once a decision exists, inspection exposes only that direction and reports `ROLLING_BACK` or `RESUMING`. Terminal `APPLIED` and `ROLLED_BACK` states expose neither mutation choice. Legacy v1 evidence exposes neither choice.

`RestoreRollback.resume(operation_id, resume_review_fingerprint)` accepts only the still-active original operation and exact current resume fingerprint. Before publishing a decision or writing a target, it proves that every retained object authenticates and every live target is exactly its sealed `BEFORE` or `AFTER` state. It publishes `action=RESUME` before the first forward write, skips targets already at `AFTER`, installs only encrypted retained after-images, and keeps the database last. It does not read the original backup archive, staging directory, normal database services, or restored SQLite contents.

After all targets match `AFTER`, the service writes an authenticated `APPLIED` terminal receipt, verifies the complete inventory again, and clears the guard. A repeated resume continues from the first remaining `BEFORE` target. If the receipt was written but finalization was interrupted, another exact resume only verifies and finalizes; it performs no target write.

The receipt/decision relationship is fail-closed. `ROLLED_BACK` requires a rollback decision. `APPLIED` allows either the original uninterrupted apply with no decision or a resume decision. An applied receipt with a rollback decision and a rolled-back receipt with a resume decision are invalid. After either recovery decision is published, the opposite operation is rejected before target mutation.

The packaged backend adds `restore-resume --operation-id <uuid> --fingerprint <sha256>`. Recovery commands continue to load only the original protected key and database-free recovery modules. The Electron controller accepts the expanded exact inspection shape, keeps **Keep workspace blocked** as default and cancel, and offers only the authenticated choices valid for the current state. It passes only the selected action's fingerprint to the hidden bundled backend, requires empty stdout from the mutating command, reinspects the terminal state, and requires the guard to be clear. Normal services start only on a later application launch.

## Security and failure boundaries

- Resume is not automatic. A native user choice is required for an initially interrupted operation and for continuation after relaunch.
- Unknown, missing, linked, redirected, oversized, unauthenticated, or externally changed target/object bytes leave the workspace blocked.
- A resume decision is durable before the first resumed target write and cannot become rollback; the inverse remains true.
- Resume uses only the active operation's sealed after-images. Deleted or changed staging files and archives are irrelevant to the recovery write path.
- Cooperative exclusive workspace ownership prevents a second recovery command from entering concurrently.
- Timeout, stderr, unexpected stdout, process failure, stale inspection, missing original key, or ambiguous post-command observation never permits normal startup.
- Forward resume does not make multi-file replacement atomic, merge work created after the guard, prove arbitrary hardware power-loss durability, or authorize bypassing the compiled restore-history admission policy that ran before guard activation.

## Consequences

- A user can explicitly finish or undo one exact interrupted v2 restore from the same authenticated evidence.
- Recovery can converge after interruption at every target boundary without rereading external restore inputs.
- The stored v2 prepared intent, image, decision, and receipt formats remain backward compatible; no database migration is required.
- Installed-app protocol and physical power/interruption acceptance remain release-lab gates even when source and packaged protocol tests pass.

## Alternatives rejected

- Automatically resuming at startup would silently choose a destructive direction.
- Reusing the rollback fingerprint for resume would make the reviewed action ambiguous.
- Allowing decision replacement would permit partial forward and rollback flows to switch direction across crashes.
- Rereading staging or backup paths would detach recovery from the sealed active operation and reintroduce mutable external inputs.
- Opening the restored database to decide whether to resume could consume SQLite recovery state and expand the recovery-only trust boundary.
