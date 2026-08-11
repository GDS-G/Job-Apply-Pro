# Production readiness completion audit

## Audit basis

This audit maps the documented Phase 12 exit criteria to direct evidence. It deliberately distinguishes source completion, packaged-candidate validation, signed-release validation, and authorized live-integration validation.

| Requirement | Implementation evidence | Validation evidence | Result |
| --- | --- | --- | --- |
| Performance and stress testing | Bounded diagnostic queries, workflow limits, startup deadline | 2,000-job test under 3 seconds; packaged startup under 60 seconds; backend coverage gate at least 80% | Source/packaged candidate complete |
| Security testing and threat model | `SECURITY.md`, `docs/threat-model.md`, strict boundaries | pnpm audit, pip-audit, Gitleaks, CodeQL for Python and JavaScript/TypeScript, encryption/auth/privacy tests | Source complete; maintenance `main` Security run green at `df11fff` |
| Accessibility | Semantic renderer and UI Automation exposure | axe serious/critical gate plus real packaged-window inspection | Candidate complete; human contrast/keyboard review remains release-lab evidence |
| Signed installer | Electron Builder NSIS, `forceCodeSigning=true`, Authenticode verifier | Unsigned local candidate correctly reports `NotSigned` and is rejected by metadata script | Implementation complete; signed artifact blocked by certificate |
| Automatic updates | Explicit check/download/install state machine, signature verification, downgrade rejection | Pure policy tests and packaged UI inspection | Source complete; signed end-to-end update requires two signed versions |
| Failure injection | Fail-closed state, encryption, browser, provider, restore and migration boundaries | `docs/failure-injection-matrix.md` | Automated rows complete; named lab rows remain |
| Portal regression schedule | Weekly/on-demand portal, browser, Reference ATS, and challenge workflow | JUnit artifact workflow | Complete for sanitized replay/loopback scope |
| User documentation | User guide, threat model, release/rollback runbook, ADRs | Repository review and Google Docs mirror | Complete |
| Support diagnostics/telemetry | Typed authenticated diagnostics, bounded error telemetry, explicit redacted export | Redaction test, stress test, packaged post-restore diagnostic check | Complete for local support scope |
| Release and rollback procedure | Version/tag enforcement, signed build, SPDX SBOM, hashes, inventories, staged publication | Workflow syntax/CI; exact signed rollback drill | Implementation complete; signed drill blocked by certificate/prior release |
| Real Windows desktop validation | Bundled backend, Edge channel, NSIS candidate | Real unpacked window launch, accessibility readback, backend connection, clean shutdown | Unsigned candidate complete |
| Required integrations | Production-disabled catalog, encrypted OAuth/PKCE adapters, and supervised exact-origin execution | Sanitized replays, loopback Reference ATS, deterministic provider HTTP tests, supervised portal policy tests | Source boundaries implemented; external provider authorization, terms approval, and sanitized live evidence remain |

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

### Maintenance refresh integration

PR #28 merged the independently validated release head `e048c9e237233a966afb224ae7d109df583165f3` as `main` commit `df11fff62d7c42d0b4bbfdc31766f7118b79be22`; the two commits have identical trees. The [pull-request CI run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31512966833) passed the complete Windows validation and packaging workflow, while its [Security run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31512966805) passed dependency audit, secret scanning, and both CodeQL analyses. The post-merge [CI run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31513466807) repeated the entire validation and packaging workflow successfully on `main`, and the corresponding [Security run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31513466743) passed all four required security jobs.

The eleven compatible or intentionally declined Dependabot PRs were closed after #28 merged. Dependabot vulnerability alerts and automated security updates are enabled, with no open Dependabot, code-scanning, or secret-scanning alerts at this audit. Node type declarations remain on the Node 24 major, and Vite remains on the Vite 7 line supported by electron-vite 5. The obsolete `models/Llama-3.1-8B` gitlink is removed from the superproject because no application code references it and it had no `.gitmodules` definition; local model assets remain ignored and are not deleted by this cleanup.

### Product completion audit correction

The authoritative feature and roadmap tabs contain long-term requirements beyond the completed Phase 0–12 vertical slices. Therefore, “source-complete” is no longer used as a claim about the entire product. `docs/requirements-traceability.md` records implemented, replay-only, externally gated, partial, and explicitly deferred scope. Portal Readiness `v0.12.2-alpha.1` begins closing the remaining source gaps by expanding every named portal replay profile and exposing replay-versus-live coverage without granting production authority.

### Portal Readiness local validation

`Portal Readiness v0.12.2-alpha.1` was validated with Node 24.14.0, pnpm 11.16.0 against the pnpm 11 lockfile, and Python 3.12.13. Formatting, linting, strict TypeScript and mypy checks, all 57 backend tests at 81.26% coverage, all 4 desktop tests, and the production build passed. The packaged Python backend was rebuilt and passed the frozen-runtime smoke test; the unpacked Windows application and NSIS installer were then built successfully. Both pnpm audit and pip-audit reported no known dependency vulnerabilities; pip-audit correctly skipped only the unpublished local `job-apply-pro-backend` package at `0.12.2a1`.

The unsigned local installer `Job-Apply-Pro-0.12.2-alpha.1-x64.exe` is 163,114,408 bytes with SHA-256 `2A4E23D34318F25C5BD48AADF503789533C267B8C15692AAFC2658AB9223579F`. Its bundled backend executable is 16,596,227 bytes with SHA-256 `67C2E806EF615E4D422CF1BBBDC2F714B667B3ED8CFFAE62B36AF17509FE096E`. Authenticode reports `NotSigned` for both, as expected when local packaging is deliberately run without release credentials. The generated update metadata identifies `0.12.2-alpha.1` and the matching 163,114,408-byte installer; it is validation evidence only and must not be published as a production update.

### Portal Readiness remote integration

PR #30 validated exact release head `b0768dd6fca84ca3e396ecba12583100fec89f6f` and merged it as `main` commit `fce7c0812d8c6e41a0ef0b6f0d099ba5bdb24cc0`. The [pull-request CI run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31517677655) passed the complete Windows build, test, frozen-backend smoke, unpacked-package, and artifact workflow. Its [Security run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31517677759) passed dependency audit, secret scan, and both CodeQL languages. Post-merge [main CI](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31518887422) and [main Security](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31518887483) both passed, and the dependency graph update also succeeded.

### Provider Connectivity local validation

`Provider Connectivity v0.13.0-alpha.1` was validated with Node 24.14.0, pnpm 11.16.0 against the pnpm 11 lockfile, and Python 3.12.13. Formatting, linting, strict TypeScript and mypy checks, all 62 backend tests at 81.44% coverage, all 4 desktop tests, and the production Electron build passed. The frozen Python backend and unpacked Windows application were rebuilt, and the packaged-backend smoke test passed. Both pnpm audit and pip-audit reported no known dependency vulnerabilities; pip-audit correctly skipped only the unpublished local `job-apply-pro-backend` package at `0.13.0a1`.

The unsigned local installer `Job-Apply-Pro-0.13.0-alpha.1-x64.exe` is 163,144,265 bytes with SHA-256 `B68AC4CB53A95E969FAFD98C00F1D1C16BD9DE1046CBCF44728DB32D3F0A2D56`. Its bundled backend executable is 16,622,761 bytes with SHA-256 `BE8CCDC18435483492D0EB5ED80FA4E9227298BDF4B3365FF8E03AE52BC17617`. Authenticode reports `NotSigned` for both, as expected when local packaging is deliberately run without release credentials. The generated update metadata identifies `0.13.0-alpha.1` and the matching 163,144,265-byte installer; it is validation evidence only and must not be published as a production update.

### Provider Connectivity remote integration

PR #31 validated exact release head `ef22b8787fe6b76e4ff7d83639829bfb814d9e6c` and merged it as `main` commit `67a6c9167ce2b9883888f78a3a566d4a0522508c`. The [pull-request CI run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31521138267) and [Security run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31521138318) passed. Post-merge [main CI](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31521725271), [main Security](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31521725235), and the dependency-graph update also passed.

### Supervised Portal Execution local validation

`Supervised Portal Execution v0.14.0-alpha.1` adds default-off, per-portal supervised execution with visible persistent browser profiles, exact-origin containment, append-only per-step evidence, manual challenge boundaries, and separately gated fingerprint-bound final submission. The implementation includes migration `20260811_0011`, authenticated start/capture/submit/stop APIs, typed desktop IPC, a native confirmation dialog, and deterministic policy coverage.

The validated environment used Node 24.14.0, pnpm 11.16.0, and Python 3.12.13. Formatting, linting, strict TypeScript and mypy checks, all 66 backend tests at 81.40% coverage, all 4 desktop tests, and the production Electron build passed. The frozen Python backend passed its packaged health smoke test, and both the unpacked Windows application and NSIS installer were rebuilt.

The unsigned local installer `Job-Apply-Pro-0.14.0-alpha.1-x64.exe` is 163,171,144 bytes with SHA-256 `64364A02ACBADAB9BD0E3407BA2A669DFC564D7F0DA81BC7E12454BCF15D6FD0`. Its bundled backend executable is 16,642,157 bytes with SHA-256 `7F6A68BD64829424645B65BED300B04AA419307D6BBE21B36C0826EB61929EE5`. Authenticode reports `NotSigned` for both, as expected for a local candidate built without release credentials. Generated update metadata identifies `0.14.0-alpha.1` and the matching installer size; it is validation evidence only and must not be published as a production update.

### Supervised Portal Execution remote integration

PR #32 validated exact release head `ff6663a73c8a22f9c56c693a40e58cffc1bfb7c8` and merged it as `main` commit `d38eeb3af56ada78986f89b0c1dc111d3184bc06`. The [pull-request CI run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31524692869) and [Security run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31524692639) passed. Post-merge [main CI](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31525260902), [main Security](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31525260757), and [dependency-graph update](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31525264514) also passed.

### Document Generation & Retention validation

`Document Generation & Retention v0.15.0-alpha.1` adds deterministic DOCX/PDF generation from locked application-approved evidence, fingerprint-bound native review, encrypted generated versions, durable generation audits, and exact submitted-version retention. Migration `20260811_0012` adds generation and submitted-document evidence tables. The Reference ATS fixture now retains the exact upload version only after filename verification, explicit final approval, and identifier-backed confirmation.

The validated environment used Node 24.14.0, pnpm 11.16.0, and Python 3.12.13. Formatting, linting, strict TypeScript and mypy checks, all 67 backend tests at 81.58% coverage, all 4 desktop tests, migration repeatability, and the production Electron build passed. The final desktop flow displays every output paragraph and confines optional decrypted export to Electron main plus a native owner-selected destination. Both pnpm audit and pip-audit reported no known dependency vulnerabilities; pip-audit skipped only the unpublished editable local backend package.

The first frozen-backend smoke correctly exposed that the previous PyInstaller spec excluded ReportLab, which became a runtime dependency when PDF generation was added. The spec now collects ReportLab modules and data. After rebuilding, the packaged backend passed migration, encrypted backup, staged offline restore, post-restore migration/restart, health, and diagnostics smoke. The unpacked Windows application and NSIS installer then rebuilt successfully.

The unsigned local installer `Job-Apply-Pro-0.15.0-alpha.1-x64.exe` is 166,585,875 bytes with SHA-256 `D746870FF0B7A3270964F7AE36675B8FC5ACA09114B73D4B39135E795F484BE2`. Its bundled backend executable is 18,245,833 bytes with SHA-256 `CBC06C81B754580477B27AC9C2B1EA39840C8DF7AB54AB06F9C9109FA35827AA`. Authenticode reports `NotSigned` for both, as expected for a local candidate built without release credentials. Generated update metadata identifies `0.15.0-alpha.1` and the matching installer size; it is validation evidence only and must not be published as a production update.

### Document Generation & Retention remote integration

PR #33 validated exact release head `688e3cfe4467deb3459b2ce65f0844d814c18877` and merged it as `main` commit `aed3fa9d4d3610260de14d400a3d22c07f8ce4fe`. The [pull-request CI run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31529394365) and [Security run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31529394253) passed. Post-merge [main CI](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31529982822), [main Security](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31529982982), and [dependency-graph update](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31529986661) also passed.

### Document Ingestion Resilience validation

`Document Ingestion Resilience v0.16.0-alpha.1` adds opt-in legacy DOC conversion through an exact LibreOffice executable, opt-in scanned-PDF OCR through bounded PDFium rendering and an exact Tesseract executable, user-visible extraction warnings, DOCX archive expansion checks, and explicit parser provenance. ADR-0025 records the fixed-argument, no-shell, secret-excluding minimal environment, isolated-workspace, timeout, resource-limit, licensing, and human-review boundaries. ReportLab is now an explicit runtime dependency, and the frozen backend includes PDFium plus the wheel's required license material.

The validated environment used Node 24.14.0, pnpm 11.16.0, and Python 3.12.13. Formatting, linting, strict TypeScript and mypy checks, all 80 backend tests at 81.75% coverage, all 4 desktop tests, the production Electron build, pnpm audit, and pip-audit passed. A regression test proves child document helpers receive a minimal environment that excludes `JAP_MASTER_KEY` and `JAP_API_TOKEN` and redirects home/temp/app-data paths into the disposable workspace. The frozen backend includes `pypdfium2_raw/pdfium.dll` and `third-party-licenses/pypdfium2`, and passed the packaged health smoke. The unpacked Windows application and NSIS installer rebuilt successfully. LibreOffice and Tesseract were not installed on the validation workstation, so real-helper execution remains an explicit owner-machine prerequisite rather than claimed evidence.

The unsigned local installer `Job-Apply-Pro-0.16.0-alpha.1-x64.exe` is 169,580,980 bytes with SHA-256 `BBF4F97714B9F5738DFF93A7884397D4B3CDD54B7CADE242D3A494194C9E97B3`. Its bundled backend executable is 18,405,502 bytes with SHA-256 `F99913C42399FE8F35CCA92F993A5A6D85D71D03DA848D547B3D969ACD4CEC3B`. Authenticode reports `NotSigned` for both, as expected for a local candidate built without release credentials. Generated update metadata identifies `0.16.0-alpha.1` and the matching installer size; it is validation evidence only and must not be published as a production update.

### Document Ingestion Resilience remote integration

PR #34 validated exact release head `a817f44383ce9dfe142ad4090246d50d8f3ca3f9` and merged it as `main` commit `5408af3f64463b883641861ac0309d33ac309389`. The [pull-request CI run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31532974537) and [Security run](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31532974538) passed. Post-merge [main CI](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31533602224), [main Security](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31533602218), and [dependency-graph update](https://github.com/GDS-G/Job-Apply-Pro/actions/runs/31533606377) also passed on the exact merge commit.

### Provider Data Resilience validation

`Provider Data Resilience v0.17.0-alpha.1` adds an authenticated Gmail/Outlook message-sync operation and desktop control, encrypted provider/message deduplication, bounded Gmail/Outlook/Google Calendar/Outlook Calendar pagination, Outlook attachment-name metadata without content download, strict Microsoft Graph continuation URL validation, iterative bounded Gmail MIME traversal, and normalized resource-limit failures. ADR-0026 records the continuation, response, item, attachment, MIME, token-origin, encryption, and live-provider boundaries.

The validated environment used Node 24.14.0, pnpm 11.16.0, and Python 3.12.13. Formatting, linting, strict TypeScript and mypy checks, all 86 backend tests at 82.01% coverage, all 5 desktop tests, the production Electron build, pnpm audit, and pip-audit passed. Provider fixtures prove Google token and Microsoft full-next-link pagination, attachment metadata paging, duplicate suppression, off-origin next-link rejection, repeated-token rejection, oversized-response rejection, and MIME-part rejection. PyInstaller packaging, PDFium binary and license collection, frozen-backend health smoke, unpacked Windows app packaging, and NSIS packaging passed.

The unsigned local installer `Job-Apply-Pro-0.17.0-alpha.1-x64.exe` is 169,587,935 bytes with SHA-256 `8EE7B617F20217A75DE88290A499ADB9B25FE7AA1B92155C3B0EC06259613661`. Its bundled backend executable is 18,410,821 bytes with SHA-256 `323DA46B3C042CA75CD7580B6395C52AEEA0A33CFBC9175E159340CE498A4A8F`. Authenticode reports `NotSigned` for both, as expected for a local candidate built without release credentials. Generated update metadata identifies `0.17.0-alpha.1` and the matching installer size; it is validation evidence only and must not be published as a production update. Remote integration evidence will be added after the exact release commit passes the required GitHub checks.

## Current release classification

`Provider Data Resilience v0.17.0-alpha.1` is the current Windows alpha source candidate under validation. It preserves the bounded-document, evidence-bound generation, Portal Readiness, Provider Connectivity, supervised execution, and production-hardening baselines while adding bounded provider reads and encrypted message sync. It is not feature-complete or a stable production release: provider configuration import/validation UX, delta/webhook synchronization, desktop notifications, richer document layout/templates/ranking, portal-specific mappings, cross-platform packaging, and other traceability items remain source work. Signing, provider registration/authorization, legal/terms and quota approval, authorized live evidence, owner-installed helper validation, and physical release-lab evidence remain external gates. Credentials pasted into chat are not an automation or secret-storage route; live validation requires owner-controlled browser sign-in, with MFA and one-time codes completed by the owner. The signed release workflow must not be dispatched and no portal catalog entry may set `production_enabled=true` until the relevant source and external controls exist.

## External launch evidence still required

1. A protected GDS-G Windows signing certificate configured as GitHub release secrets without exposing the certificate password in chat, source, logs, or artifacts.
2. A signed current-version installer whose Authenticode subject and SHA-256 checksum match the release record.
3. A second signed candidate or prior signed release to prove update and rollback behavior end to end.
4. Provider-specific legal/terms approval, granted scopes, validation ownership, and sanitized evidence for every portal, mail provider, and calendar provider claimed as production-tested. Account passwords remain owner-controlled and are entered manually rather than stored in source, documentation, CI, or chat-driven automation.
5. Attached release-lab evidence for the manual rows in `docs/failure-injection-matrix.md`, including offline network, expired login, unavailable Edge, locked database, write denial/storage pressure, sleep/resume, uninstall/reinstall, update, and rollback.
6. ~~Named support and incident-response ownership with a private vulnerability-reporting route.~~ Resolved: the solo `@GDS-G` maintainer owns support and incident response, and GitHub Private vulnerability reporting is enabled.

Until evidence groups 1-5 exist, the application remains alpha. Supervised portal capability and automated final submission stay disabled by default; mail/calendar writes require reviewed OAuth scopes, explicit mutation confirmation, and authorized validation. None is claimed as production-ready.
