# Changelog

All notable changes follow Keep a Changelog conventions and Semantic Versioning.

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
