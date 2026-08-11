# Product requirements traceability

## Purpose and authority

This audit maps the current repository to the authoritative **Job Apply Pro Documentation** Google Doc. It supplements the phase-oriented release notes; it does not narrow the long-term product scope. Explicit current user direction, accepted ADRs, and versioned contracts remain higher priority than older implementation notes when they conflict.

The earlier phrase "source-complete" meant that the planned Phase 0-12 vertical slices existed in source form. It did **not** prove that every long-term functional requirement, named live integration, target operating system, or release-acceptance gate was complete. Portal Readiness `v0.12.2-alpha.1` removed that ambiguity, Provider Connectivity `v0.13.0-alpha.1` closed the provider OAuth and official-adapter source gap, Supervised Portal Execution `v0.14.0-alpha.1` added a generic live-browser execution boundary, Document Generation & Retention `v0.15.0-alpha.1` added evidence-bound tailored outputs and exact submitted-version evidence, Document Ingestion Resilience `v0.16.0-alpha.1` added opt-in trusted DOC conversion plus bounded scanned-PDF OCR, and Provider Data Resilience `v0.17.0-alpha.1` adds bounded provider pagination, mail synchronization, and attachment-name metadata without claiming live-provider production compatibility.

## Status meanings

- **Implemented and automated** - production source exists and deterministic tests cover the stated boundary.
- **Implemented for controlled fixtures** - executable source exists, but validation is restricted to local or sanitized fixtures.
- **Implemented, externally gated** - source exists, but completion requires provider authorization, terms approval, live evidence, a signing certificate, or physical release-lab evidence.
- **Partial** - useful source exists, but one or more explicit requirements remain unimplemented.
- **Deferred by roadmap** - the authoritative roadmap explicitly permits deferral until the automation core is proven.

## Current requirement matrix

| Requirement area | Current status | Repository evidence | Work still required |
| --- | --- | --- | --- |
| Repository, governance, versioning, and protected CI | Implemented and automated | `AGENTS.md`, `.github/`, `build.json`, ADR-0002, branch protection, required CI/security checks | Maintain current checks and release records |
| Core data, repositories, migrations, encryption, workflow state, checkpoints, and append-only events | Implemented and automated | `backend/src/job_apply_pro/domain`, `storage`, `security`, Alembic migrations, core/workflow/encryption tests | Continue expanding persisted schemas with new product functions |
| Sandboxed Electron shell and authenticated localhost boundary | Implemented and automated | Electron main/preload/renderer, authenticated FastAPI routes, strict contracts, renderer/API security tests | Broader interaction-level desktop testing and final human accessibility review |
| Browser runtime, observations, verified actions, traces, takeover, and recovery | Implemented, externally gated | Isolated Playwright worker, browser runtime service, exact-origin enforcement, persistent visible profiles, browser and supervised execution tests | Authorized live profiles, portal-specific recovery evidence, native-dialog and sleep/restart lab validation |
| Candidate evidence, resume import, claims, answer provenance, retrieval, and locking | Partial | Knowledge domain/service/repository; DOC/DOCX/PDF/RTF/TXT/Markdown extraction; isolated LibreOffice conversion; bounded PDFium/Tesseract OCR; warning provenance; adversarial archive/helper tests | Richer multi-column/layout parsing, broader real-world import corpus, and owner validation of external helper installations |
| Tailored resume/cover-letter generation and exact submitted-document retention | Implemented and automated | Evidence-only preview/generation service, DOCX/PDF renderer, fingerprint approval, encrypted versions, generation/submission audit tables, desktop review flow, Reference ATS retention, and deterministic tests | Richer templates and semantic ranking remain improvements; authorized live portal upload evidence remains externally gated |
| Provider-independent AI gateway, routing, privacy, budgets, cache, and structured output | Partial | AI domain, OpenAI-compatible/local adapter, registry, service, prompts, AI gateway tests | Separately implemented secondary cloud provider, broader stable evaluations, live-provider validation, optional local runtimes |
| Reference ATS discovery-through-confirmation vertical slice | Implemented and automated | `portals/reference_ats.py`, `ReferencePortalService`, loopback fixture and portal vertical-slice tests | Retain as the safe executable regression reference |
| LinkedIn, Indeed, Monster, CareerBuilder, Dice, ZipRecruiter, Glassdoor, Workday, Taleo, Greenhouse, and company-career support | Implemented, externally gated | Production-disabled catalog, replay corpus, supervised run state/evidence repository, exact-origin runtime, authenticated API, native confirmation UI, and policy tests | Authorized live fingerprints; portal-specific mappings, terms and rate-limit approval; regression evidence; production enablement per capability |
| CAPTCHA, questionnaire, assessment, and quiz framework | Implemented for controlled fixtures | Challenge domain, detection, answer mapping, routing, durable service, API, renderer, and challenge tests | Authorized live-provider/tool routing and real timed/visual workflow evidence |
| Gmail, Outlook, Google Calendar, and Outlook Calendar | Implemented, externally gated | Common contracts; encrypted OAuth/PKCE session and token persistence; refresh/revocation; official adapters; bounded pagination and response limits; authenticated mail sync; encrypted provider/message deduplication; Outlook attachment-name metadata without content download; consent/scope/sync UI; HTTP provider tests | Owner/provider client registration, configuration import/validation UX, Google verification or Microsoft administrator consent where required, sandbox/live validation, attachment-content policy, delta/webhook synchronization, quota/rate-limit approval, and live evidence |
| Application tracking, reports, model cost, portal health, diagnostics, help, and daily scheduling | Implemented and automated for local records | Operations/communication/support services, renderer dashboard, export and reconciliation tests | Broader UX depth, real-provider health, desktop notifications, and user acceptance testing |
| Encrypted local backup, schedules, verification, staged/offline restore | Implemented and automated | Backup/operations services, offline restore CLI, migrations and recovery tests | Optional encrypted Google Drive/OneDrive transports and physical failure-injection rows |
| Signed entitlement and payment boundaries | Partial; payment deferred by roadmap | Signed entitlement verification, development license state, fail-closed payment interface | Commercial provider integration is deferrable; production entitlement issuance remains external |
| Windows packaging, updates, diagnostics, security, and performance hardening | Implemented, externally gated | PyInstaller backend, Electron Builder NSIS, update policy, SBOM/release workflow, audits, CodeQL, coverage and stress tests | Authenticode certificate, two signed builds, installer/update/rollback lab evidence, remaining manual failure injections |
| macOS and Linux releases | Partial architecture; packages not implemented | OS boundaries and local-first architecture avoid Windows-only business logic | macOS signing/notarization and Linux packaging/runtime validation; Windows remains primary |
| Broad Firefox/Safari, commercial payments, multi-device sync, cloud orchestration, fine-tuning, multi-user administration, and large-scale analytics | Deferred by roadmap | Development Roadmap section 16 | Implement after the automation core and primary Windows release meet their gates |

## Supervised portal acceptance boundary

The replay corpus continues to require job search, job detail, application form, identifier-backed confirmation acceptance, and identifier-free confirmation rejection for every named portal. Supervised execution adds these invariants:

1. automation, supervised execution, and specific portal allowlisting are separate default-off gates;
2. a live run is restricted to exact approved origins, with HTTP allowed only for loopback fixtures;
3. every capture and automated action records an append-only sequence, page fingerprint, origin, classification, and non-sensitive action fingerprint;
4. login, MFA, CAPTCHA, assessments, legal attestations, signatures, site changes, and user takeover are manual boundaries;
5. automated final submission has another default-off gate and requires the current fingerprint, exactly one recognized submit control, native desktop confirmation, and the exact approval phrase; and
6. only an identifier-backed confirmation records `SUBMISSION_CONFIRMED`; any ambiguity records `SUBMISSION_UNCERTAIN`.

These controls are source capability, not provider permission. `production_enabled` remains false, and `live_validated_page_types` remains empty until authorized, sanitized provider-specific evidence exists.

## Next source-controlled implementation order

1. Expand desktop notifications, provider configuration import/validation UX, delta/webhook synchronization, broader interaction tests, and authorized live-provider health evidence.
2. Add richer document layout parsing, templates, and semantic ranking only through the governed AI boundary, while preserving evidence IDs, deterministic fallbacks, preview fingerprints, and explicit approval.
3. Add portal-specific mappings only from authorized supervised evidence, with terms, limits, capability ownership, and stop conditions recorded per portal.
4. Complete signed Windows release, update/rollback, and physical failure-injection acceptance when the external prerequisites exist.

## External evidence that cannot be replaced by source tests

- An authorized Windows Authenticode certificate stored only in protected GitHub secrets.
- A first and second signed installer for update and rollback verification.
- Provider application registrations, approved scopes, and provider-specific legal/terms approval.
- Owner-controlled browser/OAuth sign-in, including direct handling of MFA, CAPTCHA, security codes, legal attestations, and signatures.
- Authorized, sanitized portal fingerprints and outcomes captured during an approved validation window.
- Physical Windows release-lab evidence for native dialogs, sleep/resume, network loss, storage pressure, installer, updater, and rollback behavior.

Passwords pasted into chat, source files, documentation, CI variables, replay fixtures, or application configuration are not provider connection configuration and must never be consumed by automation.
