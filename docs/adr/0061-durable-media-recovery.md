# ADR-0061: Durable media recovery

## Status

Accepted for the Durable Media Recovery `v0.51.0-alpha.1` source milestone. Supplements ADR-0059 and supersedes ADR-0060's in-memory-only cleanup and cross-invocation recovery limitations. This decision does not establish production readiness or live-provider acceptance.

## Context

The previous `finally` boundary attempted immediate deletion and stopped gateway retries after uncertain retention, but a process crash discarded local uploaded-file ownership. A later invocation could upload again, and restoring an older database could erase any new local obligation. A lost finalization response cannot safely identify a remote resource: provider-wide listing, guessed names, reuploading, and waiting for provider expiry are not deletion evidence.

## Persistence and credential identity

Migration `20260814_0023`, following `20260812_0022`, creates `ai_media_cleanup`. `storage/models.py:MediaCleanupRow` stores a local UUID, original provider ID, opaque credential fingerprint (the `account_fingerprint` field), invocation/recovery owner token, state, optional encrypted resource identifier, attempt count, bounded internal reason code, lease/retry timestamps, and creation/update timestamps. Indexes support credential admission and due recovery scans. There are no candidate foreign keys or media-content columns.

`storage/media_cleanup_repository.py:MediaCleanupRepository` owns fresh sessions for each operation; its commits are independent of gateway/cache and feature-service transactions. SQLite `BEGIN IMMEDIATE` serializes admission and conditional state changes. No database transaction spans a provider request. New media intent is committed before upload start and before any image bytes are transmitted. A database/key failure fails closed before a new upload; it is not permission to run an unjournaled adapter.

`services/media_cleanup.py:account_fingerprint()` hashes the exact API-key bytes with SHA-256, then supplies that digest together with provider kind and validated base URL to the keyed `SensitiveDataCipher.blind_index()` under `ai-media-account`. Hashing first preserves case and whitespace distinctions that the blind index's text normalization would otherwise erase. Provider configuration IDs are deliberately excluded: aliases and renaming must not bypass an existing obligation, and an identical credential under a renamed entry may recover it. Neither raw keys nor their unkeyed digest are persisted. This is a credential identity, not a verified provider-account identifier: different API keys may belong to the same remote account, but the application cannot prove that. Changed or missing credentials cannot turn another credential's 404 into successful cleanup of the original upload; key rotation remains fail-closed until the original identity or independently verified review is available.

Validated `files/{id}` resource names are stored only in AES-GCM envelopes bound to `ai-media:{local-record-id}:{provider-id}:{account-fingerprint}`. The queue never stores image bytes, upload-session URLs, file URIs, display names, prompts, provider bodies, or raw exception text. Local UUIDs and safe status metadata remain readable for recovery visibility even when a resource cannot be decrypted. Successful deletion clears the encrypted resource while retaining a status tombstone; the queue is not a media cache.

## Ownership and state transitions

`ai/media_journal.py:MediaJournal` defines one invocation's `begin`, `register`, `abandon_before_upload`, `renew`, and `cleanup` operations. `DurableMediaJournal` implements those operations over the repository. `GeminiProvider.complete()` and `_upload_media()` receive a fresh journal from the configured factory; media calls without durable storage are rejected. `api/routes/ai.py:get_ai_gateway()` and `api/routes/knowledge.py:get_knowledge_service()` both inject this boundary through `build_ai_registry()`.

Admission rejects any unresolved record for the same credential fingerprint belonging to another owner, and any non-active or expired record even for the current owner. A single invocation may own multiple active image records, subject to the existing four-image request limit. Reusing the exact credentials under another provider configuration ID does not bypass this gate. Different credential fingerprints remain isolated, without claiming that they identify different remote accounts. The original provider ID remains bound to the encrypted resource and displayed as its historical label. These controls govern new media transfer; text-only requests and read-only status are not cleanup mutations.

| Current state | Event and required evidence | Result |
| --- | --- | --- |
| None | Independent committed intent and admitted credential identity | `UPLOADING`, unknown resource, active lease |
| `UPLOADING` | Valid returned resource name; same unexpired owner | Encrypted identifier, `IN_USE`, renewed lease |
| `UPLOADING` | Caller knows no media bytes were sent; same unexpired owner | `DELETED` / `NOT_UPLOADED`; no remote deletion claim |
| `UPLOADING` | Invocation relinquishes, or expired intent is claimed without a name | `MANUAL_REVIEW` / `UNKNOWN_UPLOAD` |
| `IN_USE` | Owner relinquishes or expired ownership is claimed | `DELETE_PENDING`; exact known-resource deletion only |
| Due `DELETE_PENDING` | Atomic recovery claim | New owner token and lease; competing claims lose |
| Claimed known resource | Official fixed-origin DELETE returns 200, 204, or 404 | `DELETED` / `DELETION_CONFIRMED`; encrypted identifier cleared |
| Claimed known resource | Delete not confirmed | `DELETE_PENDING` / `DELETE_FAILED`, incremented attempts and scheduled retry |
| Claimed known resource | Envelope authentication, key/context, or identifier validation fails | `MANUAL_REVIEW` / `UNREADABLE_RESOURCE`; ciphertext preserved |
| Unknown `MANUAL_REVIEW` | Independent operator verification, exact phrase, unchanged timestamp | `DELETED` / `MANUALLY_REVIEWED`; local acknowledgment, not programmatic deletion evidence |

Mutators recheck token, state, and unexpired lease before changing owned work. Leases last 20 minutes and are renewed before lifecycle phases and before/after interaction processing. Recovery cannot claim an unexpired active record. A stale owner cannot register a resource, continue a later phase, or report normal success after ownership is lost. Normal cleanup relinquishes each record, atomically reclaims it, and attempts deletion in reverse upload order. If durable registration or an ownership transition fails after a valid remote name was observed, best-effort cleanup may still delete that exact locally held name, but the durable obligation remains unresolved and the invocation fails. A failed cleanup does not skip other known resources.

The 20-minute lease is a recovery ownership boundary, not a hard real-time network deadline. An interrupted or suspended process can exceed it while a request is already in flight; lease rejection prevents subsequent work or a success claim but cannot undo bytes already transmitted.

## Deletion-only recovery and response limits

`MediaCleanupService.recover()` builds currently configured enabled Gemini credential identities, then calls `list_recovery_candidates(..., accounts=..., include_unknown=True)` with a set of fingerprints and a limit of 100. Fingerprint filtering happens before the SQL limit, so more than 100 stale credential records cannot permanently starve a later matching record. An identical configured credential may recover a record with a historical provider label after configuration renaming. Unknown expired intents are eligible for local manual-review classification even when their provider was removed; this requires neither decrypting an identifier nor sending a request. Listing candidates and public status never decrypts resource names.

Each known resource is claimed independently, decrypted only after the matching-credential boundary, and passed to `GeminiProvider.delete_uploaded_media()`. Recovery never calls upload, interaction, embeddings, file listing, or model retry/fallback. A bad row does not prevent independent rows from being attempted. Missing credentials or local key access skip that configured runtime while leaving known obligations visible; other identities and no-network classification of unknown intents can still progress. An invalid configuration document or unavailable database can defer a recovery cycle without dropping records.

`main.py` starts `run_media_cleanup_worker()` at lifespan startup. The worker executes blocking recovery outside the event loop, attempts at most two DELETE operations per cycle, and waits 60 seconds after a cycle before the next automatic pass. The explicit retry endpoint invokes the same bounded, deletion-only pass and still respects due times and current ownership. DELETE uses a 15-second HTTP timeout in recovery. Failures schedule exponential delays from 60 seconds up to 3,600 seconds; they do not trigger another upload. Shutdown signals the worker and waits for its current pass before the browser shutdown boundary; cancellation of an underlying thread is not treated as successful cleanup.

`GeminiProvider._delete_media()` accepts only 200, 204, or already-absent 404 from the validated Google endpoint, with redirects disabled. A 202 or other unconfirmed response is not successful deletion. Irrelevant DELETE bodies are closed without being consumed, preventing a trickled body from occupying the worker indefinitely. Upload-start, finalization, and interaction responses keep the 5 MiB response limit and receive monotonic deadline checks around streamed reads. HTTP socket timeouts and checks between delivered chunks are not an aggregate upload/inference/cleanup deadline or a hard cancellation guarantee for blocked transport operations.

## Public contract and operator review

The authenticated local API adds:

- `GET /api/v1/ai/media-cleanup`: read-only `{ "items": [...] }` with unresolved public records; it performs no cleanup, key lookup, or remote request.
- `POST /api/v1/ai/media-cleanup/retry`: run one bounded deletion-only pass, then return the unresolved list.
- `POST /api/v1/ai/media-cleanup/{record_id}/resolve`: UUID-bound unknown-resource acknowledgment requiring timezone-aware `expected_updated_at` and exact `confirmation: "I VERIFIED PROVIDER MEDIA CLEANUP"`; stale/ineligible review returns 409.

`domain/media_cleanup.py:MediaCleanupPublicRecord` and the TypeScript contracts expose only local ID, provider ID, state, `known_resource`, attempts, safe reason, lease/retry timestamps, and creation/update times. They exclude account fingerprints, owner tokens, ciphertext, decrypted names, API keys, URLs, and media content. The desktop main-process client and validated IPC/preload bridge present this contract through `MediaCleanupPanel` in Operations/recovery; renderer sandbox and context isolation remain unchanged. Viewing or retrying cleanup is not consent to another image upload.

Manual acknowledgment is permitted only for `MANUAL_REVIEW` records with no stored resource. It is an explicit operator assertion after independent provider review, not evidence generated by the application. It clears the local admission block and preserves the distinct `MANUALLY_REVIEWED` reason. An unreadable known-resource envelope stays preserved, cannot be acknowledged through this action, and does not automatically requeue merely because key access later returns. Protected support/recovery handling is required; deleting the row or replacing the database is not a supported workaround.

## Backup, restore, and rollback

An encrypted database backup naturally contains the journal state at its snapshot time. It cannot contain obligations created by later uploads. `services/backup.py:BackupService.apply_staged_files()` therefore calls `_require_resolved_media_cleanup()` on the original current database before any database replacement. The supported desktop path stops the API and worker, waits for process exit, and closes database handles before applying staged files. The check is an offline prerequisite, not a lock that makes live replacement safe.

The guard opens the current SQLite database read-only, preserves WAL visibility, and rejects any journal state other than exact `DELETED`, including NULL. Missing, corrupt, inaccessible, or invalid journal objects fail closed; a valid legacy database with no journal is accepted. `immutable=1` is not used because ignoring committed WAL data could hide an obligation. Staging a backup is not applying it, and document-only restore does not replace the journal. Current unresolved obligations must be recovered or independently reviewed through supported controls before database restore/rollback; the existing `.pre-restore` copy is recovery material, not permission to discard obligations.

## Verification and remaining limits

Final local validation passes 320 backend tests at 84.45% coverage and 79 desktop tests. Ruff, strict mypy (source and tests), TypeScript, workspace formatting/lint, frozen pnpm installation, production build, pnpm audit and pip-audit pass. The unpublished local Python application package is excluded from the public-package audit; its source is covered by project checks. These checks use synthetic fixtures, not live provider or portal accounts. The official [Gemini Files API reference](https://ai.google.dev/api/files) documents the fixed resource DELETE endpoint and empty successful response; bounded status acceptance, credential matching and manual-review rules are application safety decisions.

Synthetic coverage is in `test_media_cleanup_repository.py`, `test_media_cleanup_service.py`, `test_media_cleanup_restore.py`, the existing Gemini lifecycle/gateway tests, and desktop media-cleanup panel/bridge tests. It covers independent committed intent, AES-GCM context binding, wrong/stale ownership, concurrent account admission, lease expiry/renewal, unknown review, filtered bounded recovery, malformed or unreadable resources, timestamp-bound acknowledgment, deletion-only behavior, and original-database restore protection. Migration coverage exercises upgrade, repeat upgrade, downgrade/re-upgrade, and fresh-repository persistence. The local full-suite result is recorded above, and exact-runtime Windows artifact hashes and smoke results are recorded in the readiness audit. Protected CI, signing and release-lab results require separate evidence; none is inferred from local tests.

Provider-side zero retention is not guaranteed. Unknown finalization cannot be reconstructed safely; provider auto-expiry is not immediate-deletion evidence. Current credential fingerprints intentionally do not follow API-key rotation automatically. Leases do not provide hard real-time fencing of already-running remote work, and local clock/process suspension can postpone progress. Unreadable known-resource ciphertext requires protected recovery rather than an unknown-resource acknowledgment. The image boundary still lacks full image decoding/EXIF removal and processing-state polling; only supported image signatures, 5 MiB per image, four images per request, matching MIME, active files, trusted origins, current consent, and multimodal routing are claimed. Production automation remains disabled, and live Gemini, portal, signing, and physical Windows acceptance gates remain unverified unless separately evidenced.
