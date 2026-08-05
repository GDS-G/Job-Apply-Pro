# Changelog

All notable changes follow Keep a Changelog conventions and Semantic Versioning.

## [0.5.0-alpha.1] - Unreleased

### Added

- Encrypted candidate document storage with bounded PDF, DOCX, RTF, TXT, and Markdown extraction.
- Resume variants and job-family tags with evidence sources and versioned extraction metadata.
- Strict deterministic claim proposals for contact details, skills, certifications, and dated experience.
- Explicit review, correction, verification, sensitivity, permitted-use, and locked-fact controls.
- Reproducible skill-experience calculations that merge overlapping employment periods.
- Approved answer library with encrypted content, evidence requirements, reuse permission, and provenance.
- Privacy-preserving hybrid retrieval using blind token indexes and keyed deterministic vectors.
- Authenticated Candidate Knowledge API, validated desktop IPC, native import picker, and review UI.
- Candidate Knowledge migration, extraction fixtures, encryption checks, API tests, and release metadata.

### Security

- Original documents, extracted layouts, questions, answers, and retrieval content are encrypted at rest.
- Retrieval indexes contain no candidate plaintext and exclude proposed, rejected, unlocked, or superseded facts.
- Generated or extracted content cannot replace an existing locked verified canonical fact.
- Production application submission and external AI/provider integrations remain disabled.

## [0.4.0-alpha.1] - Unreleased

### Added

- Isolated Playwright browser worker with a narrow JSON-lines command boundary.
- Persistent Chromium, Google Chrome, and Microsoft Edge profile contracts.
- Minimized observations for tabs, accessibility, relevant controls, validation, dialogs, console/network failures, uploads, downloads, screenshots, and page fingerprints.
- Declarative semantic actions with preconditions, intended results, bounded retries, permissions, confirmation state, and post-action verification.
- Durable browser session/action repositories, migrations, encrypted workflow checkpoints, takeover/return, trace capture, and restart recovery.
- Authenticated browser-runtime API and read-only desktop session status.
- Deterministic multi-page fixture validation that completes across a real Chromium restart.

### Security

- Production portal origins remain locked; development sessions accept loopback origins only.
- Renderer IPC exposes browser session status but no generic browser action or network proxy.
- Browser profiles, screenshots, traces, candidate data, tokens, and runtime databases remain outside source control.

## [0.3.0-alpha.1] - Unreleased

### Added

- Managed Electron backend supervision with migration startup, readiness polling, failure status, and clean shutdown.
- Ephemeral authenticated localhost API sessions owned by the Electron main process.
- Operating-system-protected desktop master-key storage through Electron `safeStorage`.
- Validated typed IPC for candidate creation, workflow creation, queue reads, controls, and backend status.
- Live Workbench UI for encrypted profile setup, durable mock workflows, persisted events, restart recovery, and user-facing errors.
- Atomic workflow-event and application-state persistence for desktop controls.
- API authentication, Workbench control, restart-recovery, renderer, and IPC-boundary tests.

### Security

- The renderer receives no API token, encryption key, filesystem capability, database handle, or generic network proxy.
- Privileged API routes require a timing-safe token comparison when the desktop configures a token.
- Production submission and all external integrations remain disabled.

## [0.2.0-alpha.1] - Unreleased

### Added

- Core domain contracts for candidate profiles, evidence, documents, jobs, requirements, fit scores, applications, answers, checkpoints, model invocations, and errors.
- Normalized SQLite Core schema and repeatable Alembic migration.
- Repository protocols and SQLAlchemy implementations for candidates, jobs, applications, and checkpoints.
- Candidate, job, application, encrypted-backup, and resumable-checkpoint local APIs.
- AES-256-GCM envelopes with record-specific authenticated context and pluggable key providers.
- Tests for tamper detection, ciphertext-only storage, encrypted backup/restore, checkpoint resume, APIs, and migration repeatability.

### Security

- Candidate contacts and checkpoint payloads are encrypted at rest.
- The master key is loaded only when protected data is accessed and is not stored in application settings.
- Production automation and external account integrations remain disabled.

## [0.1.0-alpha.1] - Unreleased

### Added

- Foundation monorepo and reproducible toolchain.
- Secure Electron/React desktop shell.
- FastAPI backend with loopback configuration and health API.
- Canonical workflow states, transition validation, SQLite event model, and Alembic migration.
- Shared TypeScript contracts, starter tests, CI, security scanning, and governance documentation.

### Security

- Renderer sandbox and context isolation are enabled.
- Production automation and external account integrations remain disabled in this alpha.
