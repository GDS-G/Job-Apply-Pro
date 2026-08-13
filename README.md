# Job Apply Pro

Job Apply Pro is a local-first Windows desktop application for coordinating job discovery, qualification, application workflows, and durable tracking. The product keeps deterministic state, security, validation, and browser control around bounded AI-assisted tasks.

## Inherited Disabled State Guard build

The active milestone is **Inherited Disabled State Guard `v0.43.0-alpha.1`**. Native disabledness now follows HTML semantics rather than checking only the control's own attribute. A control disabled through an ancestor fieldset is identified with explicit inherited provenance and enters the existing fail-closed binding, coverage, and execution guards. Current values remain excluded.

Backup archives are encrypted before storage, authenticated with the local master key, and verified by archive and per-entry SHA-256 hashes. Database replacement is excluded from the live API: the app stages and fingerprints restore plans, then its privileged supervisor stops the backend before invoking the offline recovery command. The prior database is retained as a `.pre-restore` file. Production release jobs fail closed without a Windows signing certificate.

This remains an alpha foundation. Named portal execution is disabled by default and must be enabled per portal for an owner-approved validation window. Sign-in, MFA, CAPTCHA, assessments, legal attestations, and signatures remain direct user actions; final submission has its own disabled-by-default gate and exact confirmation flow. Catalog entries remain `production_enabled=false`, and mail/calendar writes still require reviewed OAuth authorization. See `docs/requirements-traceability.md` for the current product-scope audit.

## Architecture

```text
apps/desktop              Electron main/preload + sandboxed React renderer
backend/src/job_apply_pro FastAPI API, workflow domain, services, and storage
backend/src/job_apply_pro/browser Isolated Playwright JSON-lines worker and client
backend/src/job_apply_pro/documents Bounded document extractors and strict claim proposals
backend/src/job_apply_pro/ai Provider adapters, registry, prompts, privacy, and routing
backend/src/job_apply_pro/portals Typed portal adapters and verification contracts
backend/src/job_apply_pro/challenges Detection, answer mapping, timing, and AI routing policy
backend/src/job_apply_pro/integrations Provider-independent mail/calendar boundaries and fixtures
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

The Candidate Knowledge API is under `/api/v1/knowledge`. Supported imports are DOC, DOCX, PDF, RTF, TXT, and Markdown. DOC support is disabled until `JAP_DOCUMENT_LEGACY_CONVERTER_PATH` names an exact absolute LibreOffice `soffice` executable. Scanned-PDF OCR is disabled until `JAP_DOCUMENT_OCR_ENABLED=true` and `JAP_DOCUMENT_OCR_TESSERACT_PATH` names an exact absolute Tesseract executable; PDFium rendering remains bounded by page, DPI, and pixel limits. These external helpers never receive arbitrary command strings or run through a shell. Tailored DOCX/PDF generation requires a selected application and uses only locked verified claims approved for applications; the user reads every output paragraph and requirement gap before a fingerprint-bound native confirmation. Generated bytes and extraction data are encrypted, while an optional native save dialog exports the chosen result through Electron main without exposing bytes to the renderer. Confirmed portal uploads retain the selected version, displayed filename, SHA-256 digest, role, and upload fingerprint.

The AI Gateway API is under `/api/v1/ai`. Provider secrets, model definitions, and routing policies are supplied as local JSON through `JAP_AI_CONFIG_JSON`; never commit that value. External OpenAI-compatible endpoints require HTTPS, local endpoints require loopback, and a native `GEMINI` provider requires the exact `https://generativelanguage.googleapis.com/v1beta` base URL plus a local API key. Gemini interactions are sent with `store=false`; remote image URLs remain unsupported. An empty configuration leaves the gateway safely `not_configured`.

The reference portal API is under `/api/v1/portals`. `POST /reference/runs` prepares a loopback fixture application through `READY_TO_SUBMIT`; `POST /runs/{id}/confirm` accepts only the exact persisted review fingerprint and records confirmation only after the adapter observes its approved confirmation signal. This release does not authorize real portal submission.

The challenge API is under `/api/v1/challenges`. Detection persists the browser fingerprint, resume state, extracted questions, and timer. Suggestions come only from encrypted profile contact fields or locked approved answer-library entries. Legal attestations, signatures, and CAPTCHAs always require direct user action. Assessment completion requires verified answers, the current review fingerprint, and the fixed `COMPLETE CHALLENGE` phrase.

Connected Gmail and Outlook accounts can be read through `POST /api/v1/communications/providers/{provider}/messages/sync`. The desktop exposes this as **Sync messages** only after reviewed OAuth authorization grants read access. Initial Gmail synchronization captures mailbox history state before its bounded message read; later reads request only added-message history. Outlook tracks created messages in the Inbox through a complete provider-issued delta link. Provider reads stop after ten pages or 1,000 items, reject repeated or untrusted continuation state, and recover once when the provider declares a cursor expired. Opaque state is account-bound and encrypted locally, advances only after successful imports, and is never returned to Electron. Outlook attachment handling reads bounded filename metadata only; it does not download attachment content. Imported messages are analyzed and encrypted locally, and replayed provider message IDs reuse the existing record.

The portal catalog is available at `/api/v1/portals/catalog`, with fingerprint identification at `/identify` and sanitized replay validation at `/replays/validate`. Catalog support means the generic workflow contract is implemented and replay-tested; it does not authorize live login, application completion, or submission.

Supervised portal runs are under `/api/v1/portals/supervised`. They require `JAP_AUTOMATION_ENABLED=true`, `JAP_SUPERVISED_PORTAL_ENABLED=true`, and an exact portal in `JAP_SUPERVISED_PORTAL_ALLOWLIST`. The visible browser remains in user takeover for authentication and challenges. Automated final submission additionally requires `JAP_SUPERVISED_PORTAL_SUBMISSION_ENABLED=true`, a current review fingerprint, exactly one recognized submit control, native desktop confirmation, and identifier-backed confirmation evidence.

The Communication API is under `/api/v1/communications`. Analyses and reply drafts are encrypted at rest; message listing, draft creation, calendar planning, follow-ups, mutation audits, and daily summaries share authenticated contracts. Gmail, Outlook, Google Calendar, and Outlook Calendar adapters fail closed until local OAuth credentials and account authorization are configured. Sanitized fixture adapters are used for regression tests and never contact provider networks.

The notification center derives bounded action projections from existing workflows, challenge sessions, communications, follow-ups, backups, and desktop update state. In-app alerts remain available by default. Native delivery must be enabled in the workbench and is limited to five new alerts per 60-second refresh. Notification text is intentionally generic because Windows may show or retain it outside the application. Selecting an alert opens only its fixed local workbench destination.

Provider registration control is available under `/api/v1/communications/configuration`. The desktop can validate and import a JSON file up to 64 KiB after a native confirmation. Accepted fields are public desktop client IDs, exact loopback redirect URIs, reviewed scopes, non-secret credential references/account hints, and policy flags. The active local configuration is AES-256-GCM ciphertext in the database. `JAP_COMMUNICATION_CONFIG_JSON` remains available for managed deployments and takes precedence; when present, desktop import and clear are disabled. Start from [`docs/examples/provider-configuration.example.json`](docs/examples/provider-configuration.example.json), replace only the public client IDs, and remove providers/scopes you are not using.

## Validation

```powershell
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [the production-readiness audit](docs/production-readiness-audit.md), [the failure-injection matrix](docs/failure-injection-matrix.md), and [docs/adr](docs/adr) before extending the architecture.
