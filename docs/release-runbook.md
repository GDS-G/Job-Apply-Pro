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

### Durable media recovery acceptance

The current source milestone is `Bounded Backend Lifecycle v0.55.0-alpha.1`. ADR-0062 requires full image decoding, static-frame/dimension limits, orientation and clean PNG re-encoding before hash/upload. Verify metadata-only variants reuse the same normalized-byte cache fingerprint and malformed media receives a static input-free 422. The source and normalized image each must fit 5 MiB; no silent resizing is permitted. The readiness audit records exact-version validation, protected integration and unsigned candidate hashes separately; none establishes signing, live-provider acceptance or release-lab completion. ADR-0063 repairs frozen browser worker dispatch; require direct-worker and packaged-API loopback smoke against the backend copied into the unpacked app, not just health checks. ADR-0064 adds owned lifecycle transitions and bounded restore observation; verify its source tests and the delivered-supervisor integration test. Durable crash/relaunch restore journaling, process-tree containment and physical release-lab gaps remain separate acceptance items.

Use synthetic files and mocked provider responses first. Verify an intent is committed before transfer, validated identifiers are encrypted, known resources survive a backend interruption and receive only deletion requests after lease expiry, and unknown finalization becomes manual review without listing or reuploading files. Check same-credential admission across provider aliases, current-owner lease renewal, stale-owner rejection, changed/removed credentials, unreadable ciphertext, a locked database, and more than 100 mismatched-credential records followed by a matching identity. Different API keys cannot be assumed to identify different remote accounts; original-credential matching is deliberately conservative. Current leases are renewed for 20 minutes before lifecycle phases; recovery makes at most two deletion attempts per cycle, waits 60 seconds between cycles, uses a 15-second network timeout, and schedules failed deletion retries exponentially from 60 seconds up to 3,600 seconds. These are ownership and scheduling controls, not hard real-time end-to-end deadlines.

Verify the Operations/recovery panel exposes only safe status metadata; its retry action must not upload, invoke a model, or replay a failed request. Unknown-resource acknowledgment requires the exact phrase `I VERIFIED PROVIDER MEDIA CLEANUP` and the current record timestamp. Do not acknowledge without independent provider review; local acknowledgment is not programmatically confirmed remote deletion. Known resources with unreadable ciphertext must remain preserved and cannot be acknowledged through this unknown-only action.

For database-restore tests, stop the API and recovery worker through the supervisor and wait for process exit. Confirm the guard inspects the original current database, observes committed WAL data, and refuses replacement for any state other than exact `DELETED`, missing/corrupt/inaccessible data, or an invalid journal object. A valid older database without a journal remains compatible. Preserve the current database and key material under the existing protected backup policy; never disable the guard to install an older snapshot. Authorized live Gemini validation additionally requires owner configuration, reviewed terms/privacy/retention settings, explicit external-AI and media consent, and sanitized outcome evidence. Provider auto-expiry is not proof of immediate deletion.

## Signed publication

1. Once signing and acceptance prerequisites above are satisfied, tag the exact approved commit `v0.55.0-alpha.1` and push the tag, or dispatch **Signed Windows Release** for that ref. Do not tag or dispatch an unsigned candidate as a production release.
2. The workflow tests, builds, requires the certificate, signs the NSIS installer, generates an SPDX JSON SBOM, verifies Authenticode, creates SHA-256 checksums and dependency inventories, and only then publishes a prerelease.
3. Download the published installer on a clean supported Windows workstation. Verify `Get-AuthenticodeSignature` reports `Valid`, the subject is the expected publisher, and the SHA-256 value matches `SHA256SUMS.txt`.
4. Install, launch, perform the smoke workflow, and confirm the update metadata resolves to the same signed artifact.
5. Promote only after support ownership and known-issue notes are published. Do not describe mock-only or replay-only integrations as production-tested.

## Rollback

1. Stop Job Apply Pro and copy `%APPDATA%\Job Apply Pro` to protected recovery storage.
2. If the failure followed a data restore, preserve both `job-apply-pro.db` and `job-apply-pro.db.pre-restore` before changing either.
   Preserve the current encrypted media journal and its key as well. Resolve known-resource recovery or independently verified unknown-resource review through the current compatible version before any database replacement; a backup made before an upload cannot cancel the resulting provider obligation.
3. Uninstall the faulty application. User data is retained by installer policy.
4. Install the prior signed version and verify its publisher and checksum.
5. Start it offline. If its schema cannot open the newer database, stop it and restore the verified pre-upgrade backup through the version that created that backup; never force an unsupported schema downgrade.
6. Confirm health, record counts, encryption access, and attempted-versus-confirmed evidence before reconnecting integrations.
7. Disable or withdraw the faulty release, document the affected versions and detection window, retain diagnostics, and open the incident procedure.

Rollback is verified only when the previous signed installer and a compatible verified backup have completed this drill on a real Windows workstation. Source compatibility tests alone are not a rollback drill.
