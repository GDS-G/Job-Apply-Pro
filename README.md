# Job Apply Pro

Job Apply Pro is a local-first Windows desktop application for coordinating job discovery, qualification, application workflows, and durable tracking. The product keeps deterministic state, security, validation, and browser control around bounded AI-assisted tasks.

## Workbench build

The active milestone is **Workbench `v0.3.0-alpha.1`**. It connects the sandboxed Electron interface to the Core local service through validated IPC, supervises migrations and backend health, and provides durable mock-workflow controls and event recovery.

This build uses real encrypted local profiles and persisted workflow events, but the workflows themselves are simulated. It does not submit applications or connect to production email, calendar, AI, or job-portal accounts.

## Architecture

```text
apps/desktop              Electron main/preload + sandboxed React renderer
backend/src/job_apply_pro FastAPI API, workflow domain, services, and storage
packages/contracts        Versioned TypeScript contracts shared by desktop code
backend/migrations        Alembic-managed SQLite schema
docs/adr                  Architecture decision records
```

Electron is the presentation and privileged local process boundary. Its main process generates an ephemeral API token, stores the master key with Electron `safeStorage`, runs migrations, supervises FastAPI, and exposes a small validated IPC bridge. The renderer receives neither Node.js access, database access, API credentials, nor encryption keys. Workflow state and events are committed together before the UI receives an update.

## Local encryption key

The managed desktop creates the master key and protects it with the operating-system encryption service. For standalone backend development only, set `JAP_MASTER_KEY` to a base64-encoded 32-byte value:

```powershell
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

The plaintext key is never committed, logged, sent to the renderer, or returned by an API. The managed desktop persists only the operating-system-protected key blob. Backups contain ciphertext and require the same key to restore.

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

The desktop development command starts and supervises the backend automatically:

```powershell
pnpm desktop:dev
```

For backend-only development, provide `JAP_MASTER_KEY` and optionally `JAP_API_TOKEN`, then run:

```powershell
pnpm backend:dev
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
