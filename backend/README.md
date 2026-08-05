# Job Apply Pro backend

The backend is a loopback-only FastAPI service that owns validated business logic, workflow state, and persistence. Install it from the repository root with:

```powershell
python -m pip install -e ".\backend[dev]"
python -m alembic -c backend\alembic.ini upgrade head
```

The Browser Runtime build exposes health, runtime status, workflow controls, event history, candidate, job, application, encrypted-backup, resumable-checkpoint, and browser-session endpoints under `/api/v1`.

Browser sessions are available under `/api/v1/browser`. Session creation, observation, verified actions, action history, takeover, return, restart, and stop all use the same privileged API authentication. Production automation is locked by default, so only loopback fixture URLs are accepted.

Candidate and checkpoint routes require `JAP_MASTER_KEY`, a base64-encoded 32-byte local key. When `JAP_API_TOKEN` is configured, all `/api/v1` routes except health require the `X-Job-Apply-Pro-Token` header. The API never persists or returns either secret. OpenAPI documentation is available at `http://127.0.0.1:8765/api/docs` while the service is running.
