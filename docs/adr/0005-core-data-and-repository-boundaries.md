# ADR 0005: Core data and repository boundaries

- Status: Accepted
- Date: 2026-08-05
- Build: Core `v0.2.0-alpha.1`

## Context

The Foundation event log proved deterministic workflow transitions but did not persist the business entities required to prepare, audit, resume, or recover an application.

## Decision

Use normalized SQLite tables for candidate profiles and evidence-backed claims, document versions, canonical jobs and requirements, fit scores, applications and answers, encrypted checkpoints, model invocations, and sanitized error records. Keep Pydantic domain models independent from SQLAlchemy rows. Services depend on repository protocols; SQLAlchemy implementations own row mapping and transactions.

Workflow checkpoints are append-only per workflow and ordered by a unique sequence. Resume always selects the highest persisted sequence and authenticates its encrypted payload before returning it.

## Consequences

- Business rules can be unit tested without binding to FastAPI.
- Storage can evolve behind explicit protocols.
- Migrations are the canonical schema history and are tested through upgrade, repeated upgrade, downgrade, and re-upgrade.
- Later builds must add repositories and services for the supporting evidence, document, scoring, invocation, and error tables before those features become operational.
