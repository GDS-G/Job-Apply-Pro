# Job Apply Pro

Job Apply Pro is a local-first Windows desktop application for coordinating job discovery, qualification, application workflows, and durable tracking. The product keeps deterministic state, security, validation, and browser control around bounded AI-assisted tasks.

## AI Gateway build

The active milestone is **AI Gateway `v0.6.0-alpha.1`**. It adds one provider-independent boundary for OpenAI-compatible cloud providers, secondary compatible providers, and local llama.cpp servers; governed model routing; multimodal input; bounded function calls; strict structured output; embeddings and reranking; encrypted version-aware caching; cost/retry/fallback controls; privacy classification and redaction; six initial agent roles; and an evaluation harness.

Application services never call provider SDKs directly. External calls require an enabled routing policy and explicit consent; highly sensitive and restricted data are blocked from external providers. Model output is validated before persistence or use and cannot overwrite a locked candidate fact. Browser automation remains loopback-only, and this build does not submit applications or connect to production email, calendar, or job-portal accounts.

## Architecture

```text
apps/desktop              Electron main/preload + sandboxed React renderer
backend/src/job_apply_pro FastAPI API, workflow domain, services, and storage
backend/src/job_apply_pro/browser Isolated Playwright JSON-lines worker and client
backend/src/job_apply_pro/documents Bounded document extractors and strict claim proposals
backend/src/job_apply_pro/ai Provider adapters, registry, prompts, privacy, and routing
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
python -m playwright install chromium
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

Browser profiles default to `var/browser`, while screenshots and Playwright traces default to `var/browser-artifacts`. Encrypted candidate originals default to `var/documents` and are limited to 10 MiB per import. These paths are ignored by Git. Configure them with `JAP_BROWSER_DATA_DIR`, `JAP_BROWSER_ARTIFACT_DIR`, `JAP_DOCUMENT_DATA_DIR`, and `JAP_DOCUMENT_MAX_BYTES`; set `JAP_BROWSER_HEADLESS=false` only for supervised local debugging.

The Candidate Knowledge API is under `/api/v1/knowledge`. Supported imports are PDF, DOCX, RTF, TXT, and Markdown. Legacy binary `.doc` files must be converted with a trusted local office tool before import.

The AI Gateway API is under `/api/v1/ai`. Provider secrets, model definitions, and routing policies are supplied as local JSON through `JAP_AI_CONFIG_JSON`; never commit that value. External endpoints require HTTPS, local endpoints require loopback, and an empty configuration leaves the gateway safely `not_configured`.

## Validation

```powershell
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [docs/adr](docs/adr) before extending the architecture.
