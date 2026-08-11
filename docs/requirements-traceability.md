# Product requirements traceability

## Purpose and authority

This audit maps the current repository to the authoritative **Job Apply Pro Documentation** Google Doc. It supplements the phase-oriented release notes; it does not narrow the long-term product scope. Explicit current user direction, accepted ADRs, and versioned contracts remain higher priority than older implementation notes when they conflict.

The earlier phrase “source-complete” meant that the planned Phase 0–12 vertical slices existed in source form. It did **not** prove that every long-term functional requirement, named live integration, target operating system, or release-acceptance gate was complete. Portal Readiness `v0.12.2-alpha.1` removed that ambiguity; Provider Connectivity `v0.13.0-alpha.1` closes the provider OAuth and official-adapter source gap without claiming external authorization.

## Status meanings

- **Implemented and automated** — production source exists and deterministic tests cover the stated boundary.
- **Implemented, replay-only** — contracts and sanitized fixtures exist, but current live-provider behavior is not claimed.
- **Implemented, externally gated** — source exists, but completion requires a certificate, provider registration, authorization, or physical release-lab evidence.
- **Partial** — useful source exists, but one or more explicit requirements remain unimplemented.
- **Deferred by roadmap** — the authoritative roadmap explicitly permits deferral until the automation core is proven.

## Current requirement matrix

| Requirement area | Current status | Repository evidence | Work still required |
| --- | --- | --- | --- |
| Repository, governance, versioning, and protected CI | Implemented and automated | `AGENTS.md`, `.github/`, `build.json`, ADR-0002, branch protection, required CI/security checks | Maintain current checks and release records |
| Core data, repositories, migrations, encryption, workflow state, checkpoints, and append-only events | Implemented and automated | `backend/src/job_apply_pro/domain`, `storage`, `security`, Alembic migrations, core/workflow/encryption tests | Continue expanding persisted schemas when new product functions are added |
| Sandboxed Electron shell and authenticated localhost boundary | Implemented and automated | Electron main/preload/renderer, authenticated FastAPI routes, strict contracts, renderer/API security tests | Broader interaction-level desktop testing and final human accessibility review |
| Browser runtime, observations, verified actions, traces, takeover, and recovery | Implemented for controlled fixtures | `backend/src/job_apply_pro/browser`, browser runtime service, Reference ATS browser tests | Authorized persistent live profiles, portal-specific recovery evidence, native-dialog and sleep/restart lab validation |
| Candidate evidence, resume import, claims, answer provenance, retrieval, and locking | Partial | Knowledge domain/service/repository, PDF/DOCX/RTF/TXT/Markdown extraction, claim and retrieval tests | Trusted legacy DOC conversion, richer layout/OCR handling, tailored resume and cover-letter generation, broader import corpus |
| Provider-independent AI gateway, routing, privacy, budgets, cache, and structured output | Partial | AI domain, OpenAI-compatible/local endpoint adapter, registry, service, prompts, AI gateway tests | A separately implemented secondary cloud provider, broader stable evaluation datasets, live provider validation, optional additional local runtimes |
| Reference ATS discovery-through-confirmation vertical slice | Implemented and automated | `portals/reference_ats.py`, `ReferencePortalService`, loopback fixture and portal vertical-slice tests | Retain as the safe executable regression reference |
| LinkedIn, Indeed, Monster, CareerBuilder, Dice, ZipRecruiter, Glassdoor, Workday, Taleo, Greenhouse, and company-career support | Implemented, replay-only | Production-disabled catalog, typed generic-agent strategy, expanded sanitized portal replay corpus | Portal-specific or supervised generic execution beyond identification; authorized live fingerprints, terms review, limits, regression evidence, and production enablement per capability |
| CAPTCHA, questionnaire, assessment, and quiz framework | Implemented for controlled fixtures | Challenge domain, detection, answer mapping, routing, durable service, API, renderer, and challenge tests | Authorized live-provider/tool routing and real timed/visual workflow evidence |
| Gmail, Outlook, Google Calendar, and Outlook Calendar | Implemented, externally gated | Common contracts; encrypted OAuth/PKCE session and token persistence; refresh/revocation boundaries; official Gmail, Microsoft Graph, Google Calendar, and Outlook Calendar adapters; consent/scope UI; deterministic HTTP provider tests | Owner/provider client registration, Google verification or Microsoft administrator consent where required, provider sandbox/live validation, attachment retrieval and richer pagination/webhook evidence |
| Application tracking, reports, model cost, portal health, diagnostics, help, and daily scheduling | Implemented and automated for local records | Operations/communication/support services, renderer dashboard, export and reconciliation tests | Broader UX depth, real-provider health, desktop notifications, and user acceptance testing |
| Encrypted local backup, schedules, verification, staged/offline restore | Implemented and automated | Backup/operations services, offline restore CLI, migrations and recovery tests | Optional encrypted Google Drive/OneDrive transport adapters and physical failure-injection rows |
| Signed entitlement and payment boundaries | Partial; payment deferred by roadmap | Signed entitlement verification, development license state, fail-closed payment interface | Commercial provider integration is explicitly deferrable; production entitlement issuance remains external |
| Windows packaging, updates, diagnostics, security, and performance hardening | Implemented, externally gated | PyInstaller backend, Electron Builder NSIS, update policy, SBOM/release workflow, audits, CodeQL, coverage and stress tests | Authenticode certificate, two signed builds, installer/update/rollback lab evidence, remaining manual failure injections |
| macOS and Linux releases | Partial architecture; packages not implemented | OS boundaries and local-first architecture avoid Windows-only business logic | macOS signing/notarization and Linux packaging/runtime validation; Windows remains the primary release |
| Broad Firefox/Safari, commercial payments, multi-device sync, cloud orchestration, fine-tuning, multi-user administration, and large-scale analytics | Deferred by roadmap | Development Roadmap section 16 | Implement after the automation core and primary Windows release meet their gates |

## Portal Readiness acceptance boundary

For every named Phase 9 portal, the replay corpus must exercise these minimum cases:

1. job search identification;
2. job-detail identification;
3. application-form identification;
4. identifier-backed confirmation accepted; and
5. otherwise identical confirmation text without an identifier rejected.

The catalog additionally defines bounded rules for login, MFA, CAPTCHA, document upload, questionnaires, assessments, submission review, and confirmation. Those rule definitions are not live compatibility claims. `production_enabled` remains false, and `live_validated_page_types` remains empty until provider-specific supervised evidence exists.

## Next source-controlled implementation order

1. Add a supervised generic portal execution plan that consumes verified observations, persists per-step evidence, and stops before legal attestations or final submission unless a current policy grants the exact action.
2. Expand document ingestion and generation, including trusted legacy DOC conversion, OCR/layout fallbacks, tailored document variants, and submitted-document retention.
3. Expand desktop interaction tests, desktop notifications, provider configuration import/validation UX, provider pagination/attachment handling, and authorized live provider health evidence.
4. Complete signed Windows release, update/rollback, and physical failure-injection acceptance when the external prerequisites exist.

## External evidence that cannot be replaced by source tests

- An authorized Windows Authenticode certificate stored only in protected GitHub secrets.
- A first and second signed installer for update and rollback verification.
- Provider application registrations, approved scopes, and provider-specific legal/terms approval.
- Owner-controlled browser/OAuth sign-in, including direct handling of MFA, CAPTCHA, security codes, legal attestations, and signatures.
- Physical Windows release-lab evidence for native dialogs, sleep/resume, network loss, storage pressure, installer, updater, and rollback behavior.

Passwords pasted into chat, source files, documentation, CI variables, or replay fixtures are not provider connection configuration and must never be consumed by automation.
