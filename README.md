# Job Apply Pro

Job Apply Pro is a local-first Windows desktop application for coordinating job discovery, qualification, application workflows, and durable tracking. The product keeps deterministic state, security, validation, and browser control around bounded AI-assisted tasks.

## Foundation build

The active foundation milestone is **Foundation `v0.1.0-alpha.1`**. It establishes the modern monorepo, secure Electron shell, React dashboard, FastAPI service, shared workflow contracts, SQLite migration, starter tests, CI, and engineering governance.

This build intentionally uses a simulated workflow queue. It does not submit real applications or connect to production email, calendar, AI, or job-portal accounts.

## Architecture

```text
apps/desktop              Electron main/preload + sandboxed React renderer
backend/src/job_apply_pro FastAPI API, workflow domain, services, and storage
packages/contracts        Versioned TypeScript contracts shared by desktop code
backend/migrations        Alembic-managed SQLite schema
docs/adr                  Architecture decision records
```

Electron is the presentation and local process boundary. FastAPI owns business logic and persistence. The renderer never receives Node.js access; its preload exposes a minimal typed bridge. Workflow state transitions are validated by deterministic domain rules before persistence.

## Prerequisites

- Windows 10 or 11
- Node.js 24 LTS
- pnpm 11
- Python 3.12 through 3.14
- Git

## Setup

```powershell
corepack enable
pnpm install
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".\backend[dev]"
python -m alembic -c backend\alembic.ini upgrade head
```

## Development

Run the backend in one terminal:

```powershell
pnpm backend:dev
```

Run the desktop application in another terminal:

```powershell
pnpm desktop:dev
```

The API listens only on `127.0.0.1:8765` by default.

## Validation

```powershell
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [docs/adr](docs/adr) before extending the architecture.
