# Job Apply Pro backend

The backend is a loopback-only FastAPI service that owns validated business logic, workflow state, and persistence. Install it from the repository root with:

```powershell
python -m pip install -e ".\backend[dev]"
python -m alembic -c backend\alembic.ini upgrade head
```

The Challenge Framework build exposes health, runtime status, workflow controls, event history, candidate, job, application, encrypted-backup, resumable-checkpoint, browser-session, candidate-knowledge, governed AI, reference-portal, and challenge-session endpoints under `/api/v1`.

Browser sessions are available under `/api/v1/browser`. Session creation, observation, verified actions, action history, takeover, return, restart, and stop all use the same privileged API authentication. Production automation is locked by default, so only loopback fixture URLs are accepted.

Candidate knowledge is available under `/api/v1/knowledge`. The backend validates and extracts PDF, DOCX, RTF, TXT, and Markdown imports, encrypts originals and extracted layouts, proposes evidence-linked claims, requires explicit review before locking facts, merges overlapping experience periods, records answer provenance, and retrieves only permitted locked knowledge. Retrieval retains its offline keyed baseline; semantic embeddings and reranking are available only through the governed AI Gateway boundary.

AI operations are available under `/api/v1/ai`. The gateway owns provider configuration, model capabilities, routing policy, prompt/schema versions, privacy checks, redaction, retries, fallback, cost limits, encrypted caching, invocation metadata, embeddings, reranking, bounded tools, six initial agents, and evaluations. OpenAI-compatible cloud, secondary compatible, and loopback llama.cpp servers share the same internal contract. With no `JAP_AI_CONFIG_JSON`, status is `not_configured` and no provider call is possible.

Reference ATS operations are available under `/api/v1/portals`. A run discovers and validates a fixture job, deduplicates it, persists requirements and fit evidence, chooses an approved resume, maps and completes the multi-page form, verifies the upload, and stops at `READY_TO_SUBMIT`. Confirmation requires the exact review fingerprint and fixed approval phrase; the adapter records `SUBMISSION_CONFIRMED` only after a strong confirmation-page signal. The adapter rejects every non-loopback origin.

Challenge operations are available under `/api/v1/challenges`. Sessions persist detection evidence, typed questions, verified answers, timers, review fingerprints, recovery events, and CAPTCHA intervention state. Answer suggestions are deterministic and limited to encrypted contact facts or locked approved application answers. Model-route responses describe the capability tier for the governed AI Gateway; challenge code never calls a provider directly.

Candidate, checkpoint, and candidate-knowledge routes require `JAP_MASTER_KEY`, a base64-encoded 32-byte local key. When `JAP_API_TOKEN` is configured, all `/api/v1` routes except health require the `X-Job-Apply-Pro-Token` header. The API never persists or returns either secret. OpenAPI documentation is available at `http://127.0.0.1:8765/api/docs` while the service is running.
