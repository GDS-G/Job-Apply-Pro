# ADR-0001: Modular local-first process architecture

- Status: Accepted
- Build: Foundation `v0.1.0-alpha.1`

## Context

Job Apply Pro must protect privileged desktop capabilities and durable applicant state while supporting replaceable browser, AI, portal, and provider integrations.

## Decision

Use a pnpm monorepo containing a sandboxed Electron/React desktop application, a loopback-only Python/FastAPI service, shared versioned contracts, and Alembic-managed SQLite persistence. Electron renderer code has no direct Node.js access. Business logic, orchestration, validation, and persistence remain in the backend.

## Consequences

The process boundary adds local lifecycle and authentication work, but it isolates crashes and privileges, keeps Python automation libraries available, and permits future worker processes without redesigning the renderer.
