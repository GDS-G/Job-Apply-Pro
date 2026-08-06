# Production readiness completion audit

## Audit basis

This audit maps the documented Phase 12 exit criteria to direct evidence. It deliberately distinguishes source completion, packaged-candidate validation, signed-release validation, and authorized live-integration validation.

| Requirement | Implementation evidence | Validation evidence | Result |
| --- | --- | --- | --- |
| Performance and stress testing | Bounded diagnostic queries, workflow limits, startup deadline | 2,000-job test under 3 seconds; packaged startup under 60 seconds; backend coverage gate at least 80% | Source/packaged candidate complete |
| Security testing and threat model | `SECURITY.md`, `docs/threat-model.md`, strict boundaries | pnpm audit, policy-wrapped pip-audit, Gitleaks, CodeQL for Python and JavaScript/TypeScript, encryption/auth/privacy tests | Source complete; remote follow-up checks required |
| Accessibility | Semantic renderer and UI Automation exposure | axe serious/critical gate plus real packaged-window inspection | Candidate complete; human contrast/keyboard review remains release-lab evidence |
| Signed installer | Electron Builder NSIS, `forceCodeSigning=true`, Authenticode verifier | Unsigned local candidate correctly reports `NotSigned` and is rejected by metadata script | Implementation complete; signed artifact blocked by certificate |
| Automatic updates | Explicit check/download/install state machine, signature verification, downgrade rejection | Pure policy tests and packaged UI inspection | Source complete; signed end-to-end update requires two signed versions |
| Failure injection | Fail-closed state, encryption, browser, provider, restore and migration boundaries | `docs/failure-injection-matrix.md` | Automated rows complete; named lab rows remain |
| Portal regression schedule | Weekly/on-demand portal, browser, Reference ATS, and challenge workflow | JUnit artifact workflow | Complete for sanitized replay/loopback scope |
| User documentation | User guide, threat model, release/rollback runbook, ADRs | Repository review and Google Docs mirror | Complete |
| Support diagnostics/telemetry | Typed authenticated diagnostics, bounded error telemetry, explicit redacted export | Redaction test, stress test, packaged post-restore diagnostic check | Complete for local support scope |
| Release and rollback procedure | Version/tag enforcement, signed build, SPDX SBOM, hashes, inventories, staged publication | Workflow syntax/CI; exact signed rollback drill | Implementation complete; signed drill blocked by certificate/prior release |
| Real Windows desktop validation | Bundled backend, Edge channel, NSIS candidate | Real unpacked window launch, accessibility readback, backend connection, clean shutdown | Unsigned candidate complete |
| Required integrations | Production-disabled catalog and credential-reference adapters | Sanitized fixtures, replay, loopback reference ATS | Not production-authorized; external accounts/legal approval required |

### Temporary Python advisory exception

The Python audit permits one machine-enforced exception: `PYSEC-2026-3552` for `cryptography==49.0.0`, expiring 2026-09-05. Its fix is assigned to unreleased 50.0.0, and the vulnerable PKCS#7 decrypt APIs are not used. The audit fails if those APIs appear, the installed version changes, the exception expires, or any unlisted advisory is found. The dependency range already permits 50.x so a fresh environment will adopt the fix once released.

## Current release classification

`Production Hardening v0.12.0-alpha.1` is a source-complete, packaged Windows alpha candidate. It is not a stable production release because no organization certificate or authorized live provider/portal accounts have been supplied. The release workflow must not be dispatched and no catalog entry may set `production_enabled=true` until those external controls exist.

## External launch evidence still required

1. A protected GDS-G Windows signing certificate configured as GitHub release secrets without exposing the certificate password in chat, source, logs, or artifacts.
2. A signed `v0.12.0-alpha.1` installer whose Authenticode subject and SHA-256 checksum match the release record.
3. A second signed candidate or prior signed release to prove update and rollback behavior end to end.
4. Named authorized test accounts, integration owners, granted scopes, and legal/terms approval for each portal, mail provider, and calendar provider claimed as production-tested.
5. Attached release-lab evidence for the manual rows in `docs/failure-injection-matrix.md`, including offline network, expired login, unavailable Edge, locked database, write denial/storage pressure, sleep/resume, uninstall/reinstall, update, and rollback.
6. Named support and incident-response ownership with a private vulnerability-reporting route.

Until all six evidence groups exist, the application remains alpha and all real portal submission/provider-write capabilities stay disabled.
