# ADR 0008: Isolated allowlisted Playwright worker

- Status: Accepted
- Date: 2026-08-05
- Build: Browser Runtime `v0.4.0-alpha.1`

## Context

Portal automation handles untrusted page content, authenticated browser storage, downloads, uploads, and potentially destructive controls. Running Playwright in FastAPI or Electron would combine those risks with the application service, desktop secrets, and renderer lifecycle.

## Decision

Playwright runs in a dedicated child process. The backend communicates through request/response JSON lines on inherited standard streams. Commands are limited to session lifecycle, observation, and validated declarative actions; arbitrary JavaScript and generic network access are not part of the protocol.

Each persistent context has a named profile, an isolated artifact directory, and an immutable origin allowlist. Navigation is checked before and after the page transition. When production automation is disabled, the service permits only loopback origins. Chromium uses the bundled Playwright browser; Chrome and Edge use their installed channels with separate profiles.

The Electron renderer can list sanitized session snapshots through typed IPC but cannot create browser actions, access profile directories, or call a generic backend route.

## Consequences

- A browser crash does not execute inside the API or renderer process.
- Authenticated storage remains reusable across worker restarts without exposing it through contracts.
- Browser installation and process startup are explicit operational dependencies.
- Cross-origin flows must be enumerated up front and fail closed when unexpected navigation occurs.
