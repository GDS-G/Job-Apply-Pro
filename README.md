# Job Apply Pro

Job Apply Pro is a local-first Windows desktop application for coordinating job discovery, qualification, application workflows, and durable tracking. The product keeps deterministic state, security, validation, and browser control around bounded AI-assisted tasks.

## Portal Adapter Expansion build

The active milestone is **Portal Adapter Expansion `v0.9.0-alpha.1`**. It adds production-disabled, replay-validated generic-agent workflows for LinkedIn, Indeed, Monster, CareerBuilder, Dice, ZipRecruiter, Glassdoor, company careers sites, Workday, Taleo, and Greenhouse. Each definition declares host boundaries, capabilities, page fingerprints, confirmation requirements, limitations, and regression status while the Reference ATS remains the only executable submission fixture.

Application services never call provider SDKs directly. External AI calls require an enabled routing policy and explicit consent; highly sensitive and restricted data are blocked from external providers. The reference ATS accepts loopback fixture origins only, and an elevated submission action requires a matching review fingerprint plus an explicit desktop confirmation. Production portals, email, and calendar accounts remain disabled.

## Architecture

```text
apps/desktop              Electron main/preload + sandboxed React renderer
backend/src/job_apply_pro FastAPI API, workflow domain, services, and storage
backend/src/job_apply_pro/browser Isolated Playwright JSON-lines worker and client
backend/src/job_apply_pro/documents Bounded document extractors and strict claim proposals
backend/src/job_apply_pro/ai Provider adapters, registry, prompts, privacy, and routing
backend/src/job_apply_pro/portals Typed portal adapters and verification contracts
backend/src/job_apply_pro/challenges Detection, answer mapping, timing, and AI routing policy
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

The reference portal API is under `/api/v1/portals`. `POST /reference/runs` prepares a loopback fixture application through `READY_TO_SUBMIT`; `POST /runs/{id}/confirm` accepts only the exact persisted review fingerprint and records confirmation only after the adapter observes its approved confirmation signal. This release does not authorize real portal submission.

The challenge API is under `/api/v1/challenges`. Detection persists the browser fingerprint, resume state, extracted questions, and timer. Suggestions come only from encrypted profile contact fields or locked approved answer-library entries. Legal attestations, signatures, and CAPTCHAs always require direct user action. Assessment completion requires verified answers, the current review fingerprint, and the fixed `COMPLETE CHALLENGE` phrase.

The portal catalog is available at `/api/v1/portals/catalog`, with fingerprint identification at `/identify` and sanitized replay validation at `/replays/validate`. Catalog support means the generic workflow contract is implemented and replay-tested; it does not authorize live login, application completion, or submission.

## Validation

```powershell
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [docs/adr](docs/adr) before extending the architecture.
