# ADR 0006: Authenticated desktop service boundary

- Status: Accepted
- Date: 2026-08-05
- Build: Workbench `v0.3.0-alpha.1`

## Context

The Core backend exposed useful localhost APIs, but a sandboxed renderer must not receive unrestricted Node.js capability, encryption keys, or a bearer credential that any injected renderer code could reuse.

## Decision

The Electron main process owns the local-service lifecycle and all privileged calls. At startup it generates an ephemeral 256-bit API token, obtains the persistent master key from an operating-system-protected `safeStorage` blob, applies Alembic migrations, launches the loopback-only FastAPI worker, and polls an authenticated runtime endpoint.

The preload exposes explicit typed Workbench operations rather than a generic request primitive. Electron main validates every IPC payload before forwarding it. FastAPI applies timing-safe token comparison to privileged `/api/v1` routes whenever `JAP_API_TOKEN` is configured. Health remains unauthenticated so the supervisor can distinguish process availability from privileged readiness.

Because the renderer sandbox cannot load an ESM preload, the build emits a CommonJS `index.cjs` preload and keeps Electron's built-in module external to the bundle. Development builds resolve the repository root from the compiled main-process location rather than the launch working directory; packaged builds use `process.resourcesPath`.

## Consequences

- Renderer compromise does not directly expose filesystem, process, database, API-token, or encryption-key capability.
- Every desktop operation has a narrow reviewable IPC contract.
- Standalone backend development can omit API authentication, but managed desktop sessions always configure it.
- Installer packaging must include the backend runtime or provide a verified runtime acquisition strategy in a later milestone.
