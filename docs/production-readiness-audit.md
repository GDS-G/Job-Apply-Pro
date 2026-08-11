# Production readiness completion audit

## Audit basis

This audit maps the documented Phase 12 exit criteria to direct evidence. It deliberately distinguishes source completion, packaged-candidate validation, signed-release validation, and authorized live-integration validation.

| Requirement | Implementation evidence | Validation evidence | Result |
| --- | --- | --- | --- |
| Performance and stress testing | Bounded diagnostic queries, workflow limits, startup deadline | 2,000-job test under 3 seconds; packaged startup under 60 seconds; backend coverage gate at least 80% | Source/packaged candidate complete |
| Security testing and threat model | `SECURITY.md`, `docs/threat-model.md`, strict boundaries | pnpm audit, pip-audit, Gitleaks, CodeQL for Python and JavaScript/TypeScript, encryption/auth/privacy tests | Source complete; final `main` Security run green at `e887e60` |
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

### Python advisory resolution

`cryptography>=50,<51` is required. Version 50.0.0 fixes `PYSEC-2026-3552`; the security workflow runs direct `pip-audit` with no advisory exceptions.

### Latest remote validation

PR #12 final head `c6caf7acc22d291a62561bbf6aaef013ec8cf177` passed dependency audit, secret scanning, Python CodeQL, JavaScript/TypeScript CodeQL, formatting, lint, strict type checking, all backend and desktop tests, the 80% coverage gate, production build, frozen-backend packaging and smoke validation, unpacked Windows packaging, and artifact upload. Commit `4e461799e7cd32a63868d8719853ccc17fafc77c` corrected a hard-coded calendar test date that had crossed from scheduled to due; the test now creates its fixture relative to the test clock and asserts both scheduled and due counts. Commit `cc0fd82774ea379257e1b7d69d0ad2310cbf945e` migrated checkout, pnpm setup, Node setup, Python setup, Gitleaks, CodeQL, and artifact upload to their Node 24-compatible action majors and added default-branch security analysis.

### Main-branch integration

Release PRs #1 through #12 were merged in version order with merge commits, each successor was retargeted to `main` only after its predecessor merged, and all named release branches were retained. The resulting `main` merge commit is `e887e60016450dbfbda6af99bf73f551f92f10a2`; its tree is identical to the independently validated PR #12 head `c6caf7acc22d291a62561bbf6aaef013ec8cf177`. The final default-branch [Security run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31509784833) passed dependency audit, secret scanning, and both CodeQL language analyses. The corresponding [CI run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31509784781) is the authoritative default-branch build, test, package, and smoke-validation record.

The `main` branch is governed for a solo maintainer: changes require a pull request and current required checks, but no approving reviewer is required while only one maintainer exists. Required conversation resolution is enabled; force pushes and branch deletion are disabled.

### Maintenance refresh local validation

`Maintenance Refresh v0.12.1-alpha.1` consolidates the compatible post-integration dependency updates into a separately versioned candidate. The validated environment uses Node 24.14, the pnpm 11 lockfile, Python 3.12, FastAPI 0.141.1, mypy 2.3.0, ReportLab 5.0.0, PyPDF 6.15.0, Starlette's `httpx2` test client, and a peer-clean Vite 7.3.6/electron-vite 5 toolchain. Node 24 type declarations remain on the Node 24 major.

Local formatting, linting, strict TypeScript and mypy checks, all 57 backend tests at 81.19% coverage, all 4 desktop tests, the production build, frozen-backend build and smoke test, unpacked Windows package, pnpm audit, and pip-audit passed. The final unsigned NSIS candidate `Job-Apply-Pro-0.12.1-alpha.1-x64.exe` is 163,110,670 bytes with SHA-256 `61B134377725C5254A44488732883EAD4A351035B2CE9AC1EBCE4B225BB8564F`; Authenticode reports `NotSigned` as required for a local candidate without release credentials. PyPDF 6.15.0 excludes `PYSEC-2026-3655` and `PYSEC-2026-3656`.

## Current release classification

`Maintenance Refresh v0.12.1-alpha.1` is the current source-complete, packaged Windows alpha candidate. It preserves the production-hardening behavior and safety boundaries while refreshing the supported build and dependency baseline. It is not a stable production release because no organization certificate or authorized live provider/portal accounts have been supplied. The release workflow must not be dispatched and no catalog entry may set `production_enabled=true` until those external controls exist.

## External launch evidence still required

1. A protected GDS-G Windows signing certificate configured as GitHub release secrets without exposing the certificate password in chat, source, logs, or artifacts.
2. A signed `v0.12.1-alpha.1` installer whose Authenticode subject and SHA-256 checksum match the release record.
3. A second signed candidate or prior signed release to prove update and rollback behavior end to end.
4. Named authorized test accounts, integration owners, granted scopes, and legal/terms approval for each portal, mail provider, and calendar provider claimed as production-tested.
5. Attached release-lab evidence for the manual rows in `docs/failure-injection-matrix.md`, including offline network, expired login, unavailable Edge, locked database, write denial/storage pressure, sleep/resume, uninstall/reinstall, update, and rollback.
6. ~~Named support and incident-response ownership with a private vulnerability-reporting route.~~ Resolved: the solo `@GDS-G` maintainer owns support and incident response, and GitHub Private vulnerability reporting is enabled.

Until evidence groups 1-5 exist, the application remains alpha and all real portal submission/provider-write capabilities stay disabled.
