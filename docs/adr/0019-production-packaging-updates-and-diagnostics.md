# ADR 0019: Production packaging, updates, and diagnostics

- Status: Accepted
- Date: 2026-08-05
- Build: Production Hardening `v0.12.0-alpha.1`

## Context

The desktop must run on a supported Windows workstation without a developer-installed Python or Node runtime. Releases must be attributable, reversible, and unable to install an unsigned update. Support data must help diagnose failures without leaking applicant content, credentials, browser state, or local paths.

## Decision

PyInstaller produces a versioned one-directory backend runtime containing migrations and the Playwright driver. Electron Builder embeds that runtime beneath `resources/backend`, packages the sandboxed Electron app as an assisted per-user NSIS installer, and leaves user data in place during uninstall. Packaged browser sessions use the installed Microsoft Edge runtime; development continues to use Playwright Chromium.

Release packaging uses `forceCodeSigning=true`. GitHub Actions requires a Windows code-signing certificate, generates an SPDX JSON SBOM from the packaged application, verifies the installer Authenticode result, generates SHA-256 checksums and dependency inventories, and only then publishes the signed artifacts. `electron-updater` checks GitHub prereleases but never downloads or installs without a user action. Publisher signature verification remains enabled, downgrades are rejected, and an update is applied only after download verification.

The authenticated diagnostics endpoint emits typed operational counts, recovery status, storage byte totals, portal replay health, model aggregate metrics, workflow event counts, sanitized error classifications and context key names, and trace basenames/sizes. The Electron main process adds platform/runtime versions and writes the explicit export with owner-only file mode. Candidate content, field values, secrets, full paths, cookies, screenshots, traces, and database rows are excluded.

## Consequences

- CI can boot and health-check the same frozen backend delivered to users.
- A release cannot be produced by the production workflow without a configured signing identity.
- System Edge becomes a supported runtime prerequisite for packaged portal automation.
- Support packages are useful for aggregate diagnosis but intentionally cannot reproduce private content failures; an explicit, separately approved trace-sharing workflow would be needed for that.
- A certificate, production accounts, and real-site authorization remain external launch inputs, not source-code defaults.
