# Job Apply Pro backend

The backend is a loopback-only FastAPI service that owns validated business logic, workflow state, and persistence. Install it from the repository root with:

```powershell
python -m pip install -e ".\backend[dev]"
python -m alembic -c backend\alembic.ini upgrade head
```

The Foundation build exposes health, simulated dashboard, workflow-transition, and event-history endpoints under `/api/v1`.
