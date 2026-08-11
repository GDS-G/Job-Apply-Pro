# Changelog

All notable changes follow Keep a Changelog conventions and Semantic Versioning.

## [0.19.0-alpha.1] - Unreleased

### Added

- Added an always-visible in-app notification center and opt-in native desktop delivery for intervention, provider-message, follow-up, backup, and update action states.
- Added a typed, privacy-safe notification projection with fixed workbench destinations, bounded 60-second polling, a maximum of 50 active items, and no more than five new native alerts per refresh.
- Added bounded local persistence for the native-delivery preference and 500 stable delivered identifiers, plus collection, deduplication, privacy, renderer interaction, and accessibility coverage.

### Changed

- Electron main now derives notification state from the existing authenticated workflow, challenge, communication, follow-up, backup, and update contracts and focuses the appropriate workbench section when an alert is selected.
- The shared contract build identity is synchronized with the active release instead of retaining the older Document Ingestion Resilience identity.

### Security

- Native notification titles and bodies never include employer, job, candidate, sender, recipient, subject, message, follow-up reason, provider identifier, diagnostic, credential, or token content.
- Native delivery is off by default, unsupported platforms retain in-app alerts, state input is limited to 64 KiB, malformed state fails closed, and notification activation accepts only four fixed local destinations.

## [0.18.0-alpha.1] - Unreleased

### Added

- Added authenticated provider-configuration status, validation, encrypted import, and clear operations with a native desktop JSON picker and explicit confirmation.
- Added an AES-256-GCM encrypted singleton configuration repository and Alembic migration, with sanitized provider/scope/capability summaries and persisted update time.
- Added desktop interaction and backend API/repository/migration coverage for configuration import, environment precedence, encryption, clearing, and secret-field rejection.

### Changed

- `JAP_COMMUNICATION_CONFIG_JSON` is now the explicit managed-deployment override; encrypted desktop configuration is used only when the environment value is absent.
- Provider connection controls now explain whether configuration is absent, encrypted locally, or environment-managed before account authorization begins.

### Security

- Configuration files are limited to 64 KiB, require at least one provider or OAuth client, reject unknown fields including passwords/tokens/client secrets, and never expose raw JSON or client IDs to the renderer or API response.
- Clearing a configuration requires native confirmation and does not claim to revoke provider consent or silently destroy retained encrypted OAuth credentials.

## [0.17.0-alpha.1] - Unreleased

### Added

- Added authenticated, desktop-accessible Gmail and Outlook message synchronization with encrypted record storage, provider/message deduplication, and sanitized fetched/imported/duplicate counts.
- Added bounded multi-page reads for Gmail, Outlook mail, Google Calendar, and Outlook Calendar using each provider's official continuation contract.
- Added Outlook attachment-name metadata retrieval without downloading attachment content, plus desktop interaction coverage for connected-provider synchronization.

### Changed

- Gmail MIME traversal is iterative and bounded; duplicate message identifiers and attachment names are suppressed before persistence or display.
- Provider reads now reject oversized responses, excessive pages/items, invalid collections, repeated continuation state, and overlong attachment or continuation metadata.

### Security

- Microsoft Graph continuation URLs must remain HTTPS on the exact Graph host, port, API path, and contain no user information or fragment before the bearer token is sent.
- Attachment reads select metadata only, ignore inline resources, never return bytes to Electron, and remain limited to 100 attachment names per message.

## [0.16.0-alpha.1] - Unreleased

### Added

- Added opt-in legacy DOC ingestion through an explicitly configured LibreOffice executable, fixed shell-free arguments, an isolated temporary profile, a strict timeout, bounded converted output, and mandatory DOCX reparsing.
- Added opt-in scanned-PDF OCR using permissively licensed PDFium rendering and an explicitly configured Tesseract executable, with page, DPI, pixel, character, block, and process-time limits.
- Added durable extraction warnings and desktop-visible import notes so incomplete page extraction is not silently treated as complete evidence.

### Changed

- Added DOC to the desktop document picker and made ReportLab an explicit runtime dependency instead of relying on the development environment during packaging.
- Added DOCX archive entry and expanded-size preflight checks before parsing, and packaged PDFium's required third-party license material with the backend.

### Security

- Converter and OCR executable paths must be absolute, point to an approved executable name, and are never executed through a shell. Password-protected PDFs remain rejected.
- External helpers receive fixed arguments and a minimal environment that excludes backend keys and tokens, run without stdin or a visible Windows console, use isolated temporary home/temp/app-data paths, and fail closed on timeout, invalid output, oversized output, or untrusted configuration.

## [0.15.0-alpha.1] - Unreleased

### Added

- Added deterministic, evidence-bound resume and cover-letter generation in DOCX and PDF formats for a selected application, using only locked verified claims approved for application use.
- Added a review preview with matched requirement IDs, unresolved required requirements, exact evidence claim IDs, and a fingerprint that must still match when the user approves generation.
- Added encrypted generated-document storage, durable generation audits, exact submitted-document evidence, and migration `20260811_0012`.
- Added desktop controls for choosing an application, document kind, output format, and variant, reading every generated paragraph, approving the exact reviewed output, and saving decrypted bytes through an owner-controlled native destination dialog.

### Changed

- Reference ATS confirmation now retains the exact verified upload version, filename, SHA-256 digest, role, and upload fingerprint after identifier-backed submission confirmation.
- Tailoring uses deterministic meaningful-token matching and excludes generic requirement language so a claim cannot qualify solely through words such as `experience`, `required`, or `preferred`.
- Generated files become ordinary encrypted candidate document versions and can be selected explicitly by later application workflows without creating new circular candidate claims.

### Security

- Generation fails closed when there is no matching locked evidence, the preview fingerprint changes, or the exact approval phrase is absent.
- Submitted-document capture rejects a changed hash, a portal-displayed filename mismatch, a cross-profile document, or a missing retention confirmation; repeated identical captures are idempotent.
- Generated bytes and extracted text remain encrypted at rest. Generation audits persist evidence identifiers and fingerprints, not candidate document text or account credentials.
- Decrypted export bytes are fetched only by the Electron main process over the authenticated loopback API after generation and are never exposed to the sandboxed renderer.

## [0.14.0-alpha.1] - Unreleased

### Added

- Added supervised live-portal runs for the named portal catalog, with visible persistent browser profiles, exact-origin allowlists, durable run state, and append-only per-step evidence.
- Added explicit manual-intervention states for login, MFA, CAPTCHA, assessments, legal attestations, final submission, and changed-site detection.
- Added authenticated portal run APIs and a desktop workbench for starting a portal, capturing a fresh page fingerprint, reviewing intervention status, submitting the exact reviewed application, and stopping while preserving the trace.

### Changed

- Named portals can now execute through a generic supervised boundary when both automation and supervised-portal gates are enabled and the specific portal is allowlisted; catalog entries remain production-disabled.
- Browser observations from start, capture, action, resume, and restart are checked against exact allowed origins. A page-driven origin escape now forces user takeover and stops automated action.
- Final submission requires a separately enabled submission gate, the current page fingerprint, exactly one recognized submit control, an exact approval phrase, and a fresh identifier-backed confirmation page.

### Security

- Passwords, MFA codes, CAPTCHA answers, legal attestations, and signatures are never application configuration. Sign-in and challenges remain direct user actions in the visible browser.
- All supervised portal capability gates default to disabled, HTTP is limited to loopback fixtures, and live evidence does not change `production_enabled` without separate terms, authorization, and release approval.
- Uncertain submission outcomes fail closed as `SUBMISSION_UNCERTAIN`; they are never reported as confirmed applications.

## [0.13.0-alpha.1] - Unreleased

### Added

- Added OAuth 2.0 Authorization Code with PKCE using one-time, encrypted authorization sessions, strict state validation, access-token refresh, and local/provider revocation boundaries.
- Added encrypted OAuth credential persistence and migration `20260811_0010`; access and refresh tokens never cross the local API or renderer contract.
- Added official HTTP adapters for Gmail, Outlook mail through Microsoft Graph, Google Calendar, and Outlook Calendar, with deterministic `httpx.MockTransport` contract coverage.
- Added desktop connection and revocation controls that open only allowlisted Google or Microsoft authorization hosts in the system browser.

### Changed

- Integration health now reports the reviewed scope count, account hint, and effective read/write boundary without exposing tokens.
- Communication configuration accepts public desktop OAuth client registrations and rejects raw client secrets, access tokens, passwords, and unknown fields.
- The loopback OAuth callback is authenticated by a high-entropy, ten-minute, one-time state capability instead of exposing the desktop API token to the system browser.

### Security

- OAuth code verifiers and token sets are encrypted with context-separated local encryption before persistence; database rows contain only opaque references and sanitized metadata.
- Requested scopes are checked against provider-specific allowlists before authorization starts, and expired sessions or replayed callbacks fail closed.
- Provider clients remain unconfigured until the owner supplies a registered public client ID and manually approves the displayed scopes; no password-based sign-in is supported.

## [0.12.2-alpha.1] - Unreleased

### Added

- Expanded every named Phase 9 portal replay profile from a single search fingerprint to search, job-detail, application-form, verified-confirmation, and identifier-free confirmation cases.
- Added automatic page-type classification across bounded portal fingerprint rules and explicit replay coverage evidence for the desktop and operations dashboard.
- Added a requirements traceability audit that separates implemented source behavior, replay-only behavior, deferred roadmap scope, and external launch evidence.

### Changed

- Raised portal fingerprint acceptance from partial signal matching to the rule-specific confidence threshold, defaulting to complete required-signal coverage.
- Added bounded fingerprint contracts for login, MFA, CAPTCHA, document upload, questionnaires, assessments, review, and confirmation pages.
- Reclassified the product honestly as an alpha foundation rather than calling the entire long-term product source-complete.

### Security

- Confirmation replay validation now proves both positive identifier-backed confirmation and fail-closed identifier-free behavior for every named portal.
- Named portal execution and provider writes remain production-disabled; replay coverage does not grant live-site authority.

## [0.12.1-alpha.1] - Unreleased

### Changed

- Refreshed the supported Node 24 and pnpm 11 development baseline, including Node 24 type declarations, accessibility tooling, icons, linting, and DOM test matchers.
- Re-aligned the desktop and contracts test workspaces to the newest Vite 7 versions supported by `electron-vite@5`; unsupported Vite 8 and Node 26 peer graphs are no longer auto-installed.
- Validated FastAPI 0.141, mypy 2, ReportLab 5, and Starlette's `httpx2` test client while retaining bounded dependency ranges.
- Moved GitHub checkout, Node setup, and Python setup workflows to their current Node 24-compatible major releases.
- Grouped future Dependabot minor and patch updates by ecosystem and capped simultaneous pull-request volume.

### Security

- Raised the PyPDF floor to 6.15.0 to exclude releases affected by `PYSEC-2026-3655` and `PYSEC-2026-3656`.
- Retained all production-disabled portal/provider boundaries and fail-closed signing requirements while refreshing audited build dependencies.
- Required the same coverage, package smoke, dependency-audit, secret-scan, and dual-language CodeQL gates as the production-hardening candidate.

## [0.12.0-alpha.1] - Unreleased

### Added

- Frozen Python backend runtime and Windows NSIS packaging with unpacked-app CI smoke coverage and release-time SPDX SBOM generation.
- Signed prerelease update checks, explicit download/install controls, and fail-closed production signing configuration.
- Redacted support diagnostics covering queue, recovery, sessions, storage, portal health, workflow events, model metrics, sanitized errors, and trace metadata.
- Controlled offline restore execution that stops and restarts the backend, verifies the reviewed SHA-256 fingerprint, and preserves the previous database.
- Automated accessibility checks, 2,000-job diagnostic stress coverage, packaged-backend health checks, and scheduled portal replay regression.
- An enforced 80% backend coverage floor, Python dependency audit, dual-language CodeQL analysis, packaged offline-restore drill, and explicit production failure-injection/readiness matrices.

### Security

- Production release packaging requires a signing certificate and verifies update publisher signatures.
- Diagnostic exports omit secrets, candidate content, error values, full paths, browser artifacts, and trace contents.
- Restore application remains outside the live HTTP API and requires a staged plan, exact fingerprint, explicit desktop confirmation, and an offline database handle.

## [0.11.0-alpha.1] - Unreleased

### Added

- Audit-reconciled application, interview, model-cost, and portal-health dashboard metrics with explicit attempted-versus-confirmed submission reporting.
- Versioned outer-encrypted local backups with consistent SQLite snapshots, encrypted document inclusion, archive and per-entry SHA-256 verification, persisted schedules, and fail-closed cloud-provider boundaries.
- Integrity-gated selective restore staging with stable review fingerprints and an offline-only application gate that preserves the prior database before replacement.
- Ed25519 signed entitlement verification, offline grace evaluation, fail-closed payment-provider interfaces, and recovery-focused in-app help.
- Authenticated operations APIs plus sandboxed desktop controls for backup creation, verification, scheduling, restore staging, reports, licensing state, and tutorials.

### Security

- Backup archives are encrypted before leaving application storage and reject tampering, unsafe paths, missing entries, and authentication failures.
- Restore application is unavailable through the live HTTP and renderer boundary; an exact staged fingerprint and fixed confirmation phrase are required by the offline service.
- Expired, invalid, absent, or development licenses retain backup verification and recovery access. Device identity uses a public-key field rather than mutable hardware addresses.

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
