# Windows release and rollback runbook

## Release prerequisites

- Clean protected release branch and version synchronized across `VERSION`, `build.json`, Python, npm packages, UI, health responses, and changelog.
- Node 24, pnpm 11, Python 3.12, supported Windows runner, and frozen dependency lock.
- Repository secrets `WIN_CSC_LINK` and `WIN_CSC_KEY_PASSWORD` configured for the authorized GDS-G Windows certificate.
- GitHub Actions release environment restricted to release maintainers.
- A verified encrypted backup and a previous signed installer available for rollback rehearsal.

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

Install the unsigned candidate only on an isolated test workstation. Verify first-start migration, restart, backup create/verify/stage/apply, diagnostics export/redaction, update UI, Edge browser launch, sleep/resume, and uninstall with retained user data. Execute failure injections for no network, backend termination, invalid token, missing staged file, changed restore fingerprint, corrupt backup, database lock, and unavailable browser runtime.

## Signed publication

1. Tag the exact approved commit `v0.12.0-alpha.1` and push the tag, or dispatch **Signed Windows Release** for that ref.
2. The workflow tests, builds, requires the certificate, signs the NSIS installer, generates an SPDX JSON SBOM, verifies Authenticode, creates SHA-256 checksums and dependency inventories, and only then publishes a prerelease.
3. Download the published installer on a clean supported Windows workstation. Verify `Get-AuthenticodeSignature` reports `Valid`, the subject is the expected publisher, and the SHA-256 value matches `SHA256SUMS.txt`.
4. Install, launch, perform the smoke workflow, and confirm the update metadata resolves to the same signed artifact.
5. Promote only after support ownership and known-issue notes are published. Do not describe mock-only or replay-only integrations as production-tested.

## Rollback

1. Stop Job Apply Pro and copy `%APPDATA%\Job Apply Pro` to protected recovery storage.
2. If the failure followed a data restore, preserve both `job-apply-pro.db` and `job-apply-pro.db.pre-restore` before changing either.
3. Uninstall the faulty application. User data is retained by installer policy.
4. Install the prior signed version and verify its publisher and checksum.
5. Start it offline. If its schema cannot open the newer database, stop it and restore the verified pre-upgrade backup through the version that created that backup; never force an unsupported schema downgrade.
6. Confirm health, record counts, encryption access, and attempted-versus-confirmed evidence before reconnecting integrations.
7. Disable or withdraw the faulty release, document the affected versions and detection window, retain diagnostics, and open the incident procedure.

Rollback is verified only when the previous signed installer and a compatible verified backup have completed this drill on a real Windows workstation. Source compatibility tests alone are not a rollback drill.
