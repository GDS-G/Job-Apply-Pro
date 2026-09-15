# Windows release and rollback runbook

## Release prerequisites

- Clean protected release branch and version synchronized across `VERSION`, `build.json`, Python, npm packages, UI, health responses, and changelog.
- Node 24, pnpm 11, Python 3.12, supported Windows runner, and frozen dependency lock.
- Repository Actions secrets `WIN_CSC_LINK` and `WIN_CSC_KEY_PASSWORD` configured for the authorized GDS-G Windows certificate. These are signing-certificate values, never portal, email, or GitHub account credentials.
- The release is initiated manually by the solo `@GDS-G` maintainer through an exact version tag or `workflow_dispatch`. A required reviewer is optional and is not configured while the project has one maintainer.
- The maintainer's GitHub account uses MFA or a passkey and has verified release-notification delivery.
- A verified encrypted backup and a previous signed installer available for rollback rehearsal.
- For Packaged Browser Runtime `v0.53.0-alpha.1` and later, migration `20260814_0023` and the cleanup journal must be available before any Gemini media transfer. A running or unresolved obligation in the current database blocks database restore; do not bypass it by replacing the database manually.

## Solo-maintainer signing-secret setup

The current workflow reads repository-level Actions secrets directly. In GitHub, open **Settings > Secrets and variables > Actions > Repository secrets**, then add these two secrets separately:

1. `WIN_CSC_LINK`: the base64 encoding of an exportable Authenticode `.pfx`/`.p12` certificate. It is not a username, account password, certificate purchase link, or ordinary web URL.
2. `WIN_CSC_KEY_PASSWORD`: the password chosen when that certificate was exported.

If GDS-G does not yet own an exportable Windows code-signing certificate, leave both secrets absent and do not dispatch the release workflow. A self-signed certificate is suitable only for isolated development and does not satisfy publication evidence. When a production `.pfx` exists, copy its base64 value directly to the clipboard without writing or printing it:

```powershell
$certificatePath = 'C:\protected\GDS-G-code-signing.pfx'
[Convert]::ToBase64String([IO.File]::ReadAllBytes($certificatePath)) | Set-Clipboard
```

Paste the clipboard into the `WIN_CSC_LINK` value field, add the secret, then clear the clipboard with `Set-Clipboard -Value ''`. Add `WIN_CSC_KEY_PASSWORD` in a second GitHub secret dialog. Never commit the certificate, encoded value, or export password. If the certificate is hardware-backed or provided through Azure Trusted Signing, update and validate the signing workflow for that provider instead of attempting to export it.

Repository secrets are appropriate for the current solo-maintainer workflow because releases are manual and the release job fails closed without signing. If maintainers are added later, move the two values to a `production-release` environment, make the job reference that environment, restrict release tags, and add a required reviewer who is not the person initiating the release.

## Account-backed integration validation

Credentials are never accepted through chat, issues, pull requests, source files, documentation, fixtures, logs, or diagnostics. Any credential disclosed through one of those channels is considered compromised and is not eligible for validation evidence.

- Portal sign-in is performed directly by the account owner in the isolated browser profile. Job Apply Pro may reuse the resulting encrypted browser session, but it does not read, record, export, or auto-fill the password itself.
- MFA, email security codes, CAPTCHAs, legal attestations, and signatures are supervised user-intervention boundaries. The workflow pauses, observes a fresh page after the user completes the challenge, and resumes only when the expected portal state is verified.
- Mail and calendar providers use OAuth with PKCE and least-privilege scopes. Raw mailbox passwords are never integration credentials.
- The application does not automatically create portal accounts. Account creation and acceptance of provider terms remain direct user actions.
- A live catalog entry remains `production_enabled=false` until the specific account, allowed actions, provider terms, test window, owner, and stop conditions are recorded and approved. Owning an account is not by itself permission to automate the provider.
- Final application submission, outbound mail, and calendar mutations retain their existing explicit-review, fingerprint, idempotency, and confirmation requirements.

## Candidate validation

Run from the repository root:

```powershell
pnpm install --frozen-lockfile
python -m pip install -e ".\backend[dev]"
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm package:backend
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_packaged_backend.ps1
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
pnpm --filter @job-apply-pro/desktop package:dir
pnpm --filter @job-apply-pro/desktop package:win
```

Install the unsigned candidate only on an isolated test workstation. Verify first-start migration, restart, backup create/verify/stage/apply, diagnostics export/redaction, update UI, Edge browser launch, sleep/resume, and uninstall with retained user data. Confirm native notifications begin disabled, enabling persists across restart, generic alerts appear in Windows Notification Center without protected source text, click activation opens the fixed workbench destination, Focus Assist behaves as expected, disabling stops future native delivery, and in-app alerts remain visible. Execute failure injections for no network, backend termination, invalid token, missing staged file, changed restore fingerprint, corrupt backup, database lock, unavailable browser runtime, unsupported notification delivery, and sleep/resume while an action is pending.

Do not reuse v0.61 counts, hashes or packaged-smoke results as v0.62 acceptance. Record the fresh `pnpm test` and `pnpm build` summaries, the backend collection total from `python -m pytest backend/tests --collect-only -q`, and the default desktop total separately from the opt-in delivered-supervisor and recovery-controller runs. The focused restore/calendar review may be repeated with:

```powershell
python -m pytest backend/tests/test_calendar_attempt_admission.py backend/tests/test_calendar_mutation_claims.py backend/tests/test_calendar_provider_admission.py backend/tests/test_calendar_oauth_pinning.py backend/tests/test_calendar_claim_migration.py backend/tests/test_forward_restore_history.py backend/tests/test_restore_history_inspection.py backend/tests/test_version_sync.py
pnpm --filter @job-apply-pro/desktop test src/main/calendar-event-ipc.test.ts src/renderer/src/CalendarEventPanel.test.tsx src/main/restore-recovery-controller.test.ts
```

Focused success does not replace the full commands above. After `pnpm package:backend`, run `scripts/test_packaged_backend.ps1` once against backend-dist and again against the backend copied into the unpacked app. Run the opt-in supervisor test against that exact delivered executable:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_packaged_backend.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_packaged_backend.ps1 -BackendDirectory release/win-unpacked/resources/backend
$env:JAP_LIFECYCLE_TEST_BACKEND = (Resolve-Path -LiteralPath 'release/win-unpacked/resources/backend/job-apply-pro-backend.exe').Path
pnpm --filter @job-apply-pro/desktop test src/main/backend-supervisor.packaged.test.ts
Remove-Item Env:JAP_LIFECYCLE_TEST_BACKEND
$env:JAP_RECOVERY_TEST_BACKEND = (Resolve-Path -LiteralPath 'release/win-unpacked/resources/backend/job-apply-pro-backend.exe').Path
pnpm --filter @job-apply-pro/desktop test src/main/restore-recovery-controller.packaged.test.ts
Remove-Item Env:JAP_RECOVERY_TEST_BACKEND
```

Record the exact commit, tool versions, command summaries, artifact sizes/hashes and Authenticode state in the production-readiness audit; no count or result is implied until those commands finish successfully.

### Calendar attempt acceptance

For `Calendar Attempt Admission v0.62.0-alpha.1`, prove that plan creation and execute are unavailable without the exact connected calendar provider, stable account identity, credential epoch, write permission and provider-specific write scope. Reviewable plans must be CREATE-only and primary-calendar-only, with invitation/reminder policies `NONE`, visibility `PRIVATE`, availability `BUSY`, attendees empty, and no recurrence, conferencing, caller-selected identifiers or unknown fields. A supplied workflow must identify an existing application. Reconnection, account/label/scope/adapter changes and ciphertext/fingerprint drift require a new plan before any claim or token access.

Exercise migration `20260913_0028`, including exact physical primary/unique/foreign-key shape, deterministic oldest matching legacy-attempt backfill, malformed relationship refusal, repeatable upgrade and fail-closed downgrade whenever any calendar plan exists. Under concurrent database sessions, exactly one `PLANNED` audit plus claim may win per plan. Exact plan/key/actor replay must return the same audit; a different key, conflicting key reuse or claim/audit/plan mismatch must not dispatch. Inject a crash after claim and a lost terminal write after provider entry: both attempts stay consumed and never redispatch automatically. Terminalization must be a one-way compare-and-set from the exact claimed `PLANNED` relationship.

For both Google and Microsoft fixtures, inspect the one POST body, fixed HTTPS target, disabled redirects/auth challenge replay, bounded identity-encoded response, deterministic provider-native duplicate-defense value and exact privacy/availability/reminder fields. Graph `dateTime` must be local wall time without an offset while its separate `timeZone` retains the reviewed IANA zone; its transaction ID must be a UUID. Invalid payload/token and clean provider rejection may be `FAILED` only through the typed definitely-not-applied path. Timeout, redirect, transport error, compression, oversize/slow/malformed response, unexpected status, invalid identifier and unexpected exception must be `UNCERTAIN`; no raw response, token, account identity or local idempotency key may appear in UI, audits or errors. `CONFIRMED` means provider acceptance and a validated identifier, not delivery or readback.

Exercise the native desktop flow with calendar-write capability absent/stale and present. Main owns the actor and idempotency key, refetches the exact plan, and shows provider, account, primary target, title, start/end, time zone, location and no-invitation wording. Cancel is the default and must be byte/network inert. A stale refetch, changed capability, duplicate click, concurrent IPC, renderer reconnect and `PLANNED`/`FAILED`/`UNCERTAIN` replay cannot create another attempt. UPDATE, attendee invitations and unattended/background scheduling remain disabled.

Restore qualification must use the schema-0028 44-table compiled policy. Backups before a calendar claim must be rejected after an attempt; a candidate that preserves the exact claim, oldest matching audit, plan/provider/kind/fingerprint and authenticated plan payload may proceed. Run these staged and final serialized-history cases without weakening v0.61 restore rollback controls. Mocked provider acceptance is not authorized live-provider evidence.

### Durable media and restore recovery acceptance

The current source milestone is `Reviewed Greenhouse Form Actions v0.67.0-alpha.1`. ADR-0077 permits exactly one backend-derived/native-confirmed selected-document upload or one ready later-stage navigation. Verify that renderer input cannot supply a URL, origin, locator, path, document identity, hash or confirmation phrase; the backend must recompute the full readiness/page/action preview immediately before execution. Upload must re-read the selected encrypted version, verify filename and SHA-256, validate decrypted bytes before staging, and clear plaintext in `finally`. Both actions must reuse durable browser-effect admission and require specialized post-observation evidence. Inject stale reviews, changed bytes/pages/controls/origins, failed results and lost postconditions; require user takeover, durable unverified evidence and no automatic retry. Navigation to confirmation must fail; final submission and ordinary/custom/legal fields retain separate gates. Verify sanitized fixtures and refusal cases, but do not call them live compatibility. Supervised execution and `GREENHOUSE` allowlisting remain disabled by default. Exact backend-dist/delivered-package smokes and supervisor/recovery protocols must be rerun for the v0.67 commit; older package evidence does not transfer. It remains alpha until protected CI/security, authorized live Greenhouse acceptance, signing and physical installed Windows results are attached; package qualification is not release acceptance. ADR-0074 continues to require one selected application and exact workflow scoping. ADR-0073 continues to require durable `PREPARED` and `DISPATCHING` ownership before browser and AI provider calls, immutable terminal outcomes, no fallback after ambiguity, startup recovery to `UNCERTAIN`, safe static errors and schema-0029 protection for both ledger tables. ADR-0062 requires full image decoding, static-frame/dimension limits, orientation and clean PNG re-encoding before hash/upload. Verify metadata-only variants reuse the same normalized-byte cache fingerprint and malformed media receives a static input-free 422. The source and normalized image each must fit 5 MiB; no silent resizing is permitted. The readiness audit records exact-version validation, protected integration and unsigned candidate hashes separately; none establishes signing, live-provider acceptance or release-lab completion. ADR-0063 repairs frozen browser worker dispatch; require direct-worker and packaged-API loopback smoke against the backend copied into the unpacked app, not just health checks. ADR-0064 adds owned lifecycle transitions and bounded restore observation; verify its delivered-supervisor integration test. ADR-0066 adds persistent restore admission and preservation of the original key. ADR-0071 adds authenticated v2 before/after images, explicit reviewed rollback, resumable rollback and terminal finalization. It does not add automatic rollback, forward-apply resume, multi-file atomicity, process-tree containment or a physical power-loss guarantee.

For v2 preparation, verify complete reviewed staged-source authentication precedes any staged SQLite query. Require the compiled 44-table schema-0028 physical history and dependency checks against one exact original byte snapshot. Verify the candidate database is deserialized only into an exact-schema `:memory:` connection, the default-deny authorizer permits only required direct bookkeeping inserts/named-column updates, and mail/calendar attempts plus broad history preservation are rechecked on the serialized result. Exercise denied schema, function, pragma, delete, trigger/view, recursive-source and unrelated-table mutation. At the maximum supported inventory, prove staged inputs are stream-checked before allocation, database/document plaintext is sealed one item at a time, the database is last, 4 MiB control-record, 512 MiB-plus-envelope object, per-side 1 GiB and 256 MiB per-file limits fail closed, and operation/global retained-evidence count/byte quotas are rechecked for each publication before guard activation or live writes. Inject every pre-guard preparation/publication failure and require deletion of only the exact newly allocated unactivated operation when safe inventory can be proved; uncertain residue must remain retained and count against later admission.

The package verifier must independently authenticate exact v2 record/source shape, operation/workspace binding, reviewed-to-applied plan identity, target order, unique deterministic object names, every referenced before/after object, original database and document preimages, receipt digest/inventory and every live applied target. It must reject an active guard, rollback decision, extra operation file, missing/extra/unreferenced object, changed live byte, wrong key/context, reparse point, hard link, oversize record/object and unexpected plaintext output. A successful forward-apply verifier run does not exercise the recovery controller. The `JAP_RECOVERY_TEST_BACKEND` opt-in closes the source-controller-to-delivered-backend command/protocol gap with synthetic data, but it mocks Electron key decryption/dialogs and is not the physical installed-app rehearsal below.

Exercise that controller separately from the packaged application with synthetic v2 evidence and the real `safeStorage` key location. Confirm a guarded launch ignores packaged project/database environment overrides, constructs no normal services, and uses only the hidden redirected console backend. Cancel must be the default for both interrupted rollback and terminal finalization and must leave the guard unchanged. Exact rollback/finalization must re-inspect the terminal state, require the guard to clear, close the app and allow normal startup only on the next launch. Missing/corrupt protected key, legacy v1 evidence, failed initial inspection, stale fingerprint and changed targets must leave the workspace blocked. If stderr, unexpected/oversized output, timeout, command failure or failed post-inspection occurs after an authorized mutating command, require the current process to close without normal startup and preserve all evidence; do not claim the guard remains, because the backend may already have completed a verified terminal transition before the controller lost trustworthy observation.

Use synthetic files and mocked provider responses first. Verify an intent is committed before transfer, validated identifiers are encrypted, known resources survive a backend interruption and receive only deletion requests after lease expiry, and unknown finalization becomes manual review without listing or reuploading files. Check same-credential admission across provider aliases, current-owner lease renewal, stale-owner rejection, changed/removed credentials, unreadable ciphertext, a locked database, and more than 100 mismatched-credential records followed by a matching identity. Different API keys cannot be assumed to identify different remote accounts; original-credential matching is deliberately conservative. Current leases are renewed for 20 minutes before lifecycle phases; recovery makes at most two deletion attempts per cycle, waits 60 seconds between cycles, uses a 15-second network timeout, and schedules failed deletion retries exponentially from 60 seconds up to 3,600 seconds. These are ownership and scheduling controls, not hard real-time end-to-end deadlines.

Verify the Operations/recovery panel exposes only safe status metadata; its retry action must not upload, invoke a model, or replay a failed request. Unknown-resource acknowledgment requires the exact phrase `I VERIFIED PROVIDER MEDIA CLEANUP` and the current record timestamp. Do not acknowledge without independent provider review; local acknowledgment is not programmatically confirmed remote deletion. Known resources with unreadable ciphertext must remain preserved and cannot be acknowledged through this unknown-only action.

Verify **External effects requiring attention** reports aggregate unresolved counts and no more than the 20 newest `PREPARED`, `DISPATCHING`, or `UNCERTAIN` records. Confirm the response and renderer omit prompts, candidate data, page/provider content, request/claim fingerprints, actors, credentials, tokens, native keys, and raw errors. Confirm there is no generic retry, clear, or resolve control. A future reconciliation action must have a provider-specific evidence contract and separate acceptance cases before it can mutate replay authority.

For database-restore tests, stop the API and recovery worker through the supervisor and wait for process exit. Require closed original and staged databases: any WAL, SHM or hot-journal sidecar blocks restore before SQLite reads; do not delete sidecars to force admission. Prove that complete plan/manifest/archive/staged-input authentication finishes before the staged SQLite file is queried. On closed storage, confirm admission rejects unresolved media obligations in either snapshot; missing/corrupt/inaccessible data; unsupported or physically altered schema, indexes, uniqueness or foreign keys; triggers/views/virtual or unknown tables; duplicate/malformed/broken relationships; unauthenticated encrypted fields; changed current rows, exact-set authority/session/cache state, or immutable document evidence. A valid older database remains compatible only when it preserves the complete compiled schema-0027 dependency graph. Preserve the current database, restore-control evidence and original key under the protected backup policy; never disable the guard or launch an older binary to bypass it. Authorized live Gemini validation additionally requires owner configuration, reviewed terms/privacy/retention settings, explicit external-AI and media consent, and sanitized outcome evidence. Provider auto-expiry is not proof of immediate deletion.

ADR-0067 acceptance requires deterministic PROCESSING-to-ACTIVE/FAILED cases, exact original resource/MIME/URI validation, a shared maximum of 30 processing GETs, one invocation-local work budget across every image and the response, and post-response-construction expiry rejection. Verify the separate 30-second cleanup allowance still traverses every durable obligation and that unresolved retention is terminal. A mocked successful deletion is not live retention evidence, and HTTPX phase/inactivity timeouts do not establish hard OS or gateway-wide cancellation.

ADR-0068 acceptance requires fixed public GET fixtures, exact source/profile binding, immutable concurrent import, stale/changed/unavailable source handling and rejected fabricated transitions. In both packaged copies, verify invalid board/posting input and a missing local import profile fail before public transport. These negative probes prove frozen routing/admission, not live Greenhouse compatibility. A recognized URL, imported posting or mock score is not permission to apply.

Forward database restore now preserves current rows and their dependency closure across 44 explicit schema-0028 tables, authenticates encrypted payloads and immutable documents, validates calendar claim relationships, and requires exact equality for mutable OAuth, provider-sync/calendar, browser/portal/challenge, configuration and AI-cache state that a restored-only snapshot could otherwise revive. The exact original byte snapshot is checked against the authenticated staged candidate before bookkeeping and against the final serialized bytes afterward; every live target is checked against its sealed `BEFORE` image immediately before guard activation. Run the dedicated backup-before-mutation, schema, relational, quota and document cases for the exact candidate. Do not present this as proof of an external action that was never durably recorded: some provider/browser/model operations still need pre-call intent journals, and automatic forward resume remains unimplemented. V2 interrupted rollback can restore only the operation's authenticated exact preimages while the original guard remains active; it cannot merge later activity or make an unsafe forward restore admissible.

## Signed publication

1. Once signing and acceptance prerequisites above are satisfied, tag the exact approved commit `v0.67.0-alpha.1` and push the tag, or dispatch **Signed Windows Release** for that ref. Do not tag or dispatch an unsigned candidate as a production release.
2. The workflow tests, builds, requires the certificate, signs the NSIS installer, generates an SPDX JSON SBOM, verifies Authenticode, creates SHA-256 checksums and dependency inventories, and only then publishes a prerelease.
3. Download the published installer on a clean supported Windows workstation. Verify `Get-AuthenticodeSignature` reports `Valid`, the subject is the expected publisher, and the SHA-256 value matches `SHA256SUMS.txt`.
4. Install, launch, perform the smoke workflow, and confirm the update metadata resolves to the same signed artifact.
5. Promote only after support ownership and known-issue notes are published. Do not describe mock-only or replay-only integrations as production-tested.

## Interrupted restore admission

For ADR-0066/ADR-0071 restores, preserve the whole workspace and original master key before any recovery action. `restore-control/active.guard` blocks normal startup, migration and updates. A v2 `restore-control/operations/<uuid>/` contains authenticated encrypted intent, every target's before/after object, an optional rollback decision and a receipt only after a terminal state was verified. The database before-image exists even for document-only restore because restore bookkeeping changes the database. Legacy v1 directories may contain only intent, a database preimage and optional completion receipt; they do not authorize document rollback. Older `.pre-restore` files are neither overwritten nor assumed authoritative.

For an installed package, reopen the same version. The active guard must route startup into the native recovery-only controller before key creation, migration, API services, renderer windows or update checks. The controller decrypts the existing OS-protected key, runs bounded authenticated inspection through the bundled console backend, and presents only fixed native choices. **Keep workspace blocked** is both the default and cancel action. Do not export or paste the protected key into a terminal.

Choose **Roll back exact restore** only after confirming that returning every operation target to its exact original state is intended. The controller passes the unchanged inspection fingerprint. The durable decision is written before rollback targets; interrupted retries skip targets already at the before state, remove only a known introduced file still at its exact after-image and restore the database last. Unknown live bytes, missing/corrupt images, links, sidecars, a stale fingerprint, an `APPLIED` receipt, wrong key or cleared/different guard remain blocked. This is rollback resume, not forward-apply resume or history merging.

Choose **Finalize exact restore state** only for an authenticated terminal `APPLIED` or `ROLLED_BACK` receipt whose complete target inventory matches live bytes. The native controller re-runs inspection after either action and requires the expected terminal state and a cleared guard, then closes the application; reopen it to start normally. Legacy v1 incomplete replacement remains manual recovery. Do not fabricate receipts or fingerprints, remove guards/sidecars, force stale ownership, generate a replacement key or launch an older version that ignores admission.

`restore-status`, `restore-inspect`, `restore-rollback` and `restore-finalize` remain strict backend protocol commands for controlled source/package testing and qualified manual recovery. They do not replace the installed native key mediation and must not be used to solicit or expose a user's protected key.

Before release, exercise database-only, document-only and combined restore in a supported local workspace. Verify hot journals are preserved even when the plan ID is invalid; missing databases do not become empty files; a staged WAL cannot supply history that would be absent from the replacement; and an interrupted operation remains blocked after a new desktop process starts. At every target-install boundary, inspect then roll back and prove exact original database/documents, database-last ordering, introduced-file removal limits and retry convergence. Successful packaged smoke must authenticate v2 intent/receipt, every referenced before/after object, the original database image, exact live terminal targets, absence of an active guard/decision after apply and exact retained draft/readiness state. V0.59's unconfigured packaged probe proves offline previews remain unsendable with zero audits after restore; actual accepted/uncertain send-history preservation is source-tested and still needs authorized packaged acceptance.

## Rollback

1. Stop Job Apply Pro and copy `%APPDATA%\Job Apply Pro` to protected recovery storage.
2. If the failure followed a data restore, preserve the database, any legacy `.pre-restore` copy, the complete `restore-control` directory, staged files and encrypted backups. If admission is blocked, stop this rollback drill and follow the interrupted-restore section; an older binary must not bypass the guard.
   Preserve the current encrypted media journal, every mail-send audit/claim and the original key. Resolve known-resource recovery or independently verified unknown-resource review through the current compatible version before any database replacement; a backup made before an upload cannot cancel the resulting provider obligation. An older snapshot must not erase a recorded mail attempt.
3. Uninstall the faulty application. User data is retained by installer policy.
4. Install the prior signed version and verify its publisher and checksum.
5. Start it offline only after confirming that it understands the current admission and external-effect history safeguards. If its schema cannot open the newer database, stop it and prepare a compatible recovery plan; never force an unsupported schema downgrade or use an old restore implementation to bypass current history checks.
6. Confirm health, record counts, encryption access, and attempted-versus-confirmed evidence before reconnecting integrations.
7. Disable or withdraw the faulty release, document the affected versions and detection window, retain diagnostics, and open the incident procedure.

Rollback is verified only when the previous signed installer and a compatible verified backup have completed this drill on a real Windows workstation. Source compatibility tests alone are not a rollback drill.
