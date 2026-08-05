# Job Apply Pro backend

The backend is a loopback-only FastAPI service that owns validated business logic, workflow state, and persistence. Install it from the repository root with:

```powershell
python -m pip install -e ".\backend[dev]"
python -m alembic -c backend\alembic.ini upgrade head
```

The Core build exposes health, simulated dashboard, workflow-transition, event-history, candidate, job, application, encrypted-backup, and resumable-checkpoint endpoints under `/api/v1`.

Candidate and checkpoint routes require `JAP_MASTER_KEY`, a base64-encoded 32-byte local key. The API never persists or returns the key. OpenAPI documentation is available at `http://127.0.0.1:8765/api/docs` while the service is running.
