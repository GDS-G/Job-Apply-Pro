# Changelog

All notable changes follow Keep a Changelog conventions and Semantic Versioning.

## [0.10.0-alpha.1] - Unreleased

### Added

- Normalized Gmail and Outlook message contracts, deterministic classification, application correlation, recruiter-response drafts, and attachment/version verification.
- Encrypted communication analyses and outbound draft payloads plus durable calendar plans, follow-up schedules, and mutation audits in Alembic migration `20260805_0008`.
- Fingerprinted, idempotent send and calendar mutation gates with provider-issued confirmation identifiers and fail-closed disabled adapters.
- Google Calendar and Outlook Calendar conflict ranking with time-zone, working-hour, attendee, meeting-link, and before/after event evidence.
- Sanitized Gmail, Outlook, and calendar replay adapters, authenticated Communication API routes, daily summaries, and desktop provider-health and message-review views.

### Security

- OAuth tokens are represented only by opaque credential references and must resolve through an operating-system credential broker; tokens never cross renderer IPC or enter SQLite.
- Message bodies, subjects, recipients, reply text, calendar details, and prior-event snapshots are authenticated ciphertext at rest.
- Live provider reads and writes are disabled by default. Every write requires an exact persisted fingerprint and idempotency key, and remains unconfirmed until the provider returns an immutable resource identifier.

## [0.9.0-alpha.1] - Unreleased

### Added

- Typed generic-agent portal definitions for LinkedIn, Indeed, Monster, CareerBuilder, Dice, ZipRecruiter, Glassdoor, company careers sites, Workday, Taleo, and Greenhouse.
- Per-portal domain boundaries, capability declarations, page fingerprints, confirmation rules, limitations, support status, and adapter versions.
- Authenticated portal catalog, page-identification, and replay-validation APIs.
- Sanitized replay corpus with per-portal fingerprint accuracy and confirmation false-positive metrics.
- Desktop portal health cards that distinguish replay validation from production enablement.

### Security

- All Phase 9 portal definitions remain production-disabled and cannot execute live actions.
- Weak fingerprints, unknown page types, unsanitized replays, and identifier-free confirmation signals fail closed.
- The loopback Reference ATS remains the only executable submission integration.

## [0.8.0-alpha.1] - Unreleased

### Added

- Durable CAPTCHA, questionnaire, quiz, and timed-assessment sessions with typed detection, question extraction, visible-timer synchronization, persisted events, and Alembic migration `20260805_0007`.
- Verified answer execution for text, select, checkbox, and true/false controls, with required, option, and character-limit validation.
- Candidate answer suggestions restricted to encrypted contact facts and locked approved application answer-library records.
- Provider-independent fast-text, strong-reasoning, multimodal, long-context, cache, and low-confidence escalation recommendations for the governed AI Gateway.
- Recovery refresh that re-observes the browser, detects challenge drift, invalidates stale verification evidence, and preserves answer values for supervised re-verification.
- Authenticated `/api/v1/challenges` routes, validated Electron IPC, and a desktop challenge panel for detection, answers, CAPTCHA handoff, review, and completion.
- Real-Playwright assessment and CAPTCHA fixtures covering timer capture, answer verification, explicit completion, saved-state resume, events, authentication, and repeatable migrations.

### Security

- CAPTCHA and legal/signature fields require direct user intervention; no solver credentials or bypass service are accepted.
- Challenge completion requires the exact current review fingerprint and fixed confirmation phrase.
- Page changes invalidate previously verified answers during recovery, and model routing remains advisory behind the AI Gateway.
- Production portal automation, production submission, email, and calendar integrations remain disabled.

## [0.7.0-alpha.1] - Unreleased

### Added

- Typed reference ATS adapter with loopback JSON discovery, browser-observed job identity validation, capability declaration, canonical field mapping, and strong confirmation rules.
- Complete persisted workflow from search, extraction, deduplication, fit scoring, eligibility, and resume selection through multi-page form completion, upload verification, review, confirmed fixture submission, and tracking.
- Portal-run, job-requirement, fit-score, workflow-event, browser-action, screenshot, confirmation-evidence, and trace persistence.
- Authenticated `/api/v1/portals` prepare, list, read, and confirm endpoints plus validated Electron IPC and a supervised desktop portal panel.
- Deterministic real-Playwright regression fixture covering job reuse, evidence-backed qualification, required fields, upload, approval mismatch, confirmation code, trace creation, and cleanup.
- Alembic migration `20260805_0006` for portal-run evidence.

### Security

- Reference ATS discovery and submission reject every non-loopback origin regardless of the broader automation setting.
- Encrypted resumes are decrypted only into a session-scoped upload directory, which is removed immediately after verified upload and again on stop.
- Submission requires an exact persisted review fingerprint and explicit phrase; a click alone can never produce `SUBMISSION_CONFIRMED`.
- Production portal automation, production submission, email, and calendar integrations remain disabled.

## [0.6.0-alpha.1] - Unreleased

### Added

- Provider-independent AI Gateway contracts and authenticated `/api/v1/ai` routes.
- OpenAI-compatible adapter shared by primary cloud, secondary cloud, and loopback llama.cpp providers.
- Capability-aware model registry and per-task routing policies with bounded retries, fallback, timeouts, and cost budgets.
- Text, multimodal input, strict structured output, bounded function calls, embeddings, and reranking.
- Versioned task-specific prompt registry with untrusted-data separation and locked-fact precedence.
- Routine, Employment Sensitive, Highly Sensitive, and Restricted privacy classifications with external-consent and redaction policy.
- AES-256-GCM encrypted, profile/source/model/prompt/schema/privacy-versioned response cache.
- Sanitized model invocation records with hashes, route, usage, costs, attempts, latency, status, and error classification.
- Coordinator, qualification, form interpretation, answer, verification, and recovery agents.
- Deterministic evaluation harness and provider, privacy, fallback, validation, cache, agent, API, and migration fixtures.

### Security

- External providers require HTTPS, explicit routing permission, and user consent; local endpoints require loopback.
- Highly Sensitive and Restricted data cannot be transmitted to external models.
- Provider secrets, prompts, candidate inputs, and plaintext outputs are excluded from invocation logs.
- Model responses and tool calls fail closed unless their declared JSON schemas validate.
- Production application submission remains disabled.

## [0.5.0-alpha.1] - Unreleased

### Added

- Encrypted candidate document storage with bounded PDF, DOCX, RTF, TXT, and Markdown extraction.
- Resume variants and job-family tags with evidence sources and versioned extraction metadata.
- Strict deterministic claim proposals for contact details, skills, certifications, and dated experience.
- Explicit review, correction, verification, sensitivity, permitted-use, and locked-fact controls.
- Reproducible skill-experience calculations that merge overlapping employment periods.
- Approved answer library with encrypted content, evidence requirements, reuse permission, and provenance.
- Privacy-preserving hybrid retrieval using blind token indexes and keyed deterministic vectors.
- Authenticated Candidate Knowledge API, validated desktop IPC, native import picker, and review UI.
- Candidate Knowledge migration, extraction fixtures, encryption checks, API tests, and release metadata.

### Security

- Original documents, extracted layouts, questions, answers, and retrieval content are encrypted at rest.
- Retrieval indexes contain no candidate plaintext and exclude proposed, rejected, unlocked, or superseded facts.
- Generated or extracted content cannot replace an existing locked verified canonical fact.
- Production application submission and external AI/provider integrations remain disabled.

## [0.4.0-alpha.1] - Unreleased

### Added

- Isolated Playwright browser worker with a narrow JSON-lines command boundary.
- Persistent Chromium, Google Chrome, and Microsoft Edge profile contracts.
- Minimized observations for tabs, accessibility, relevant controls, validation, dialogs, console/network failures, uploads, downloads, screenshots, and page fingerprints.
- Declarative semantic actions with preconditions, intended results, bounded retries, permissions, confirmation state, and post-action verification.
- Durable browser session/action repositories, migrations, encrypted workflow checkpoints, takeover/return, trace capture, and restart recovery.
- Authenticated browser-runtime API and read-only desktop session status.
- Deterministic multi-page fixture validation that completes across a real Chromium restart.

### Security

- Production portal origins remain locked; development sessions accept loopback origins only.
- Renderer IPC exposes browser session status but no generic browser action or network proxy.
- Browser profiles, screenshots, traces, candidate data, tokens, and runtime databases remain outside source control.

## [0.3.0-alpha.1] - Unreleased

### Added

- Managed Electron backend supervision with migration startup, readiness polling, failure status, and clean shutdown.
- Ephemeral authenticated localhost API sessions owned by the Electron main process.
- Operating-system-protected desktop master-key storage through Electron `safeStorage`.
- Validated typed IPC for candidate creation, workflow creation, queue reads, controls, and backend status.
- Live Workbench UI for encrypted profile setup, durable mock workflows, persisted events, restart recovery, and user-facing errors.
- Atomic workflow-event and application-state persistence for desktop controls.
- API authentication, Workbench control, restart-recovery, renderer, and IPC-boundary tests.

### Security

- The renderer receives no API token, encryption key, filesystem capability, database handle, or generic network proxy.
- Privileged API routes require a timing-safe token comparison when the desktop configures a token.
- Production submission and all external integrations remain disabled.

## [0.2.0-alpha.1] - Unreleased

### Added

- Core domain contracts for candidate profiles, evidence, documents, jobs, requirements, fit scores, applications, answers, checkpoints, model invocations, and errors.
- Normalized SQLite Core schema and repeatable Alembic migration.
- Repository protocols and SQLAlchemy implementations for candidates, jobs, applications, and checkpoints.
- Candidate, job, application, encrypted-backup, and resumable-checkpoint local APIs.
- AES-256-GCM envelopes with record-specific authenticated context and pluggable key providers.
- Tests for tamper detection, ciphertext-only storage, encrypted backup/restore, checkpoint resume, APIs, and migration repeatability.

### Security

- Candidate contacts and checkpoint payloads are encrypted at rest.
- The master key is loaded only when protected data is accessed and is not stored in application settings.
- Production automation and external account integrations remain disabled.

## [0.1.0-alpha.1] - Unreleased

### Added

- Foundation monorepo and reproducible toolchain.
- Secure Electron/React desktop shell.
- FastAPI backend with loopback configuration and health API.
- Canonical workflow states, transition validation, SQLite event model, and Alembic migration.
- Shared TypeScript contracts, starter tests, CI, security scanning, and governance documentation.

### Security

- Renderer sandbox and context isolation are enabled.
- Production automation and external account integrations remain disabled in this alpha.
