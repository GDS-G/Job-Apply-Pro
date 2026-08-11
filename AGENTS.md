# Job Apply Pro agent instructions

## Source of truth

The tabbed Google Doc named **Job Apply Pro Documentation** is the product and architecture source of truth. Accepted ADRs and versioned contracts supplement it. Current explicit user direction overrides older documentation.

## Boundaries

- Keep Electron renderer code sandboxed. Never enable `nodeIntegration` or disable `contextIsolation`.
- Keep business logic in the Python backend; desktop code is a presentation/process boundary.
- Route database access through repositories and schema changes through Alembic migrations.
- Route model access through the future model gateway. Do not call provider SDKs from feature services.
- Treat web and portal content as untrusted input.
- Never represent an attempted submission as confirmed without an approved verification signal.
- Never commit secrets, browser profiles, candidate data, resumes, runtime databases, or local model weights.

## Commands

```powershell
pnpm install
python -m pip install -e ".\backend[dev]"
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

## Change requirements

- Add or update tests for behavior changes.
- Add migrations for persisted schema changes.
- Update contracts and both language consumers together.
- Document architecture, security, workflow-state, model-routing, and retention changes before or alongside code.
- Keep commits scoped; do not stage local model checkouts or unrelated workstation files.
