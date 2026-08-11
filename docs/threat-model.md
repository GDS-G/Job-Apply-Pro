# Production threat model

## Protected assets

Candidate identity and history, resumes, answers, browser sessions, mail/calendar data, application evidence, encryption keys, API/provider credentials, backups, and release artifacts require protection. Availability of local recovery data and integrity of submission evidence are as important as confidentiality.

## Trust boundaries

| Boundary | Threats | Required controls |
| --- | --- | --- |
| Sandboxed renderer to Electron main | IPC forgery, Node escape, secret disclosure | Context isolation, sandbox, no Node integration, narrow typed IPC, validation, no tokens/keys in renderer |
| Electron main to loopback API | Local process impersonation, request tampering | Loopback bind, random per-launch token, authenticated privileged routes, explicit timeouts |
| API to SQLite/files | plaintext disclosure, traversal, corruption, locked DB | AES-256-GCM envelopes, resolved-root checks, Alembic, atomic writes, consistent backup, offline restore |
| Browser worker to portals | prompt injection, hostile DOM, cross-origin escape, false confirmation | isolated process, origin allowlist, bounded actions, fingerprints, human gates, identifier-backed confirmation |
| AI gateway to providers | data exfiltration, tool injection, unbounded cost | consent/privacy routing, redaction, schema validation, bounded tools, budgets, encrypted cache, no direct service calls |
| Mail/calendar adapters | token theft, duplicate or unintended writes | OS credential references, encrypted content, review fingerprint, idempotency key, immutable provider confirmation |
| Package/update channel | dependency tampering, unsigned installer, downgrade | frozen lockfiles, dependency/secret scans, inventory artifacts, code signing, signature verification, fail-closed release, no downgrade |
| Diagnostics/support | secret or candidate-data leakage | aggregate-only schema, value stripping, basename-only traces, explicit local export, user review |

## Abuse cases and response

- A malicious page instructs the agent to ignore policy: treat page text as data; only deterministic application policy authorizes actions.
- A click occurs without reliable confirmation: record attempted/uncertain, never confirmed, and require review.
- A backup is changed or contains traversal paths: fail verification before staging and preserve the current installation.
- The database is locked or migration fails: mark runtime degraded, do not start automation, preserve database and diagnostic evidence.
- An update is unsigned or signed by another publisher: reject installation and retain the current version.
- A diagnostic error contains a token value: export only the context key name; values never cross the diagnostics contract.
- The backend or browser process exits: surface degraded state, retain checkpoints, and require an explicit retry or restart.

## Residual risk and launch constraints

Alpha builds do not authorize live generic-portal submission. Production enablement requires named integration owners, current terms/legal review, authorized test accounts, real Windows desktop validation, portal replay plus supervised live validation, a protected signing certificate, incident-response ownership, and a rollback drill using the exact candidate installer. CAPTCHA solving and legal attestations are permanently human-only boundaries.
