# ADR-0070: Reviewed job readiness

## Status and scope

Accepted for Reviewed Job Readiness `v0.60.0-alpha.1`. This advances a saved public Greenhouse job through explicit requirements, evidence, eligibility and immutable resume review. It is local and deterministic: no AI/model registry, public request, browser action, upload or application submission. ADR-0068's immutable public source remains the input; this is not a complete named-portal adapter.

## Domain and policies

`domain/job_readiness.py` defines frozen, extra-forbidden request, preview, approval, review and snapshot contracts. `READINESS_POLICY = reviewed-job-readiness/1` versions requirements/evidence decisions; `SELECTION_POLICY = reviewed-resume-selection/1` versions document selection. Source and review fingerprints are 64-character SHA-256 values. Requests require application identity; the API also requires exact path/body identity agreement.

`SourceSpan` contains a server-issued ID and exact saved-source line. `RequirementChoice` selects a span and MANDATORY, PREFERRED or AMBIGUOUS classification; it cannot replace source text. Requirements requests contain at most 100 choices. `RequirementFinding` records SUPPORTED, CONTRADICTED or UNKNOWN plus up to 30 distinct current claim IDs. Every approved requirement must receive exactly one finding, with no unrelated requirement IDs.

`JobReadinessSnapshot` reports application/job/profile/workflow identity, historical state, support, effective status, source/spans, eligible evidence claims, latest review per kind, allowed actions and a scope notice. Effective statuses are UNSUPPORTED, REQUIREMENTS_REVIEW, QUALIFICATION_REVIEW, ELIGIBILITY_REVIEW, RESUME_REVIEW, READY and STALE. Allowed actions are REVIEW_REQUIREMENTS, REVIEW_QUALIFICATION and SELECT_RESUME, derived from current dependencies rather than caller claims.

## Exact source and evidence

`JobReadinessService._source()` accepts only `greenhouse-public` applications in DEDUPLICATED, SCORED, ELIGIBILITY_CHECKED or DOCUMENTS_SELECTED. It compares job identity/title/employer/location/URL/description hash with the immutable snapshot. Its source fingerprint includes the full saved job and normalized review. A missing or inconsistent snapshot blocks review.

Nonblank description lines become spans, preserving exact text. IDs hash source fingerprint, original line index and text, so repeated identical lines remain distinct. Empty sources or more than 500 spans fail without truncation. Renderer offsets, JavaScript/Python character-count agreement and generated requirement text are not trusted. The operator explicitly classifies employer wording; selecting lines does not certify that every requirement was found.

`_claims()` admits at most 1,000 candidate claims for local review. Each eligible claim must belong to the application's profile, be VERIFIED, locked, nonsuperseded and permitted for APPLICATIONS or ANY. A matching evidence source is mandatory. Archived/missing/cross-profile document sources are excluded. Linked immutable document bytes are decrypted and hashed, and extraction is authenticated, even for older versions or non-resume evidence. Corrupt bytes/extraction or invalid Unicode cannot support qualification.

The candidate fingerprint includes every currently eligible claim, source metadata and verified linked bytes/extraction—not merely selected evidence IDs or a score. Revocation, changed permitted use, supersession, source changes and newly eligible evidence invalidate old review. Manual evidence sources remain explicit reviewed assertions, not independent employer verification.

## Requirements and qualification decisions

`preview_requirements()` verifies the source fingerprint, unique selected span IDs and exact membership, then orders selected requirements by saved source order. `_requirements_hash()` binds policy, source and classified exact text. The preview fingerprint also includes application and prior requirements review. Approval requires `APPROVE REVIEWED REQUIREMENTS`; a new review never rewrites the public source or global job requirements.

`preview_qualification()` requires the latest valid requirements review and recomputes candidate evidence. SUPPORTED and CONTRADICTED findings require current claim links; UNKNOWN has none. Evidence links are operator judgments, not semantic inference. Mandatory and preferred supported/count totals are reported separately.

A review is evaluable only with at least one explicit mandatory criterion and no ambiguous criterion. Coverage is supported mandatory plus preferred findings divided by all findings, only when evaluable; otherwise it is null, never a perfect score for missing requirements. Eligibility requires every mandatory criterion supported. Preferred gaps can reduce coverage without defeating mandatory eligibility. Unknown/contradicted mandatory evidence prevents clearance.

`approve_qualification()` requires `APPROVE REVIEWED QUALIFICATION` and a strict boolean `approve_eligibility`. Saving an evaluable assessment may record SCORED; clearance requires the separate explicit choice and eligible preview, then records ELIGIBILITY_CHECKED. Saving an unevaluable review leaves earlier state unchanged. Review IDs and evidence fingerprints are retained with the decision.

## Immutable resume selection

`_require_qualification()` independently requires current requirements, current evidence, evaluability, eligibility and explicit eligibility approval before selection. `preview_resume()` supports RESUME only. It projects the approved exact requirements into the existing deterministic document ranking service through an internal argument, without mutating shared job requirements or bypassing evidence review.

`_document_fingerprint()` bounds the inventory to 100 documents and includes all active resumes' latest version metadata, decrypted-byte hashes and authenticated extraction. The strong selection fingerprint includes request preferences/exclusions, recommendation set, full requirements/qualification reviews, inventory, policy and previous selection. Adding a resume, changing tags, bytes or extraction invalidates review even if the apparent rank/score is unchanged.

`approve_resume()` requires `SELECT REVIEWED DOCUMENT`, the exact strong fingerprint and a version from the reviewed recommendation set. It atomically appends a SELECTION review and document-selection audit, retains the exact selected version, and advances to DOCUMENTS_SELECTED. Ranking describes text coverage/preferences, not qualifications or permission to upload.

The generic document-selection path rejects public Greenhouse jobs unless invoked internally with reviewed requirements. This closes a route around readiness approval. A previous selection and historical state remain visible after dependencies change, but effective readiness becomes STALE. Future portal consumers must require current readiness, not assume a historical DOCUMENTS_SELECTED event is still authority.

## Storage, transactions and migration

Migration `20260913_0027`, after source-bound-mail revision `20260913_0026`, adds `job_readiness_reviews`: UUID ID, application FK, kind, revision, request fingerprint, encrypted payload and timestamp. Unique constraints cover application/kind/revision and application/kind/request fingerprint. AES-GCM context binds payload to application and review IDs. Existing sources, requirements, correspondence and workflow records are preserved; no old row becomes approved. Backup schema revision becomes 0027. Development downgrade drops the new review table and is not an operational recovery procedure.

`JobReadinessRepository.write()` acquires SQLite's writer reservation through a no-op application update before expiring cached ORM objects and rereading dependencies. Review, state/events and selection audit share one transaction; individually committing generic helpers are not used. Errors roll back. Concurrent duplicate approval returns current matching review without duplicate events; superseded/stale replay is rejected.

`advance()` appends legitimate ordered milestones with actor reviewed-job-readiness and an explicit no-portal-action cause. It does not rewrite old events or move history backward. Requirements approval alone stays DEDUPLICATED. The public generic workflow transition remains denied for real jobs under ADR-0068.

## API and desktop review

Authenticated routes are under `/applications/{application_id}/job-review`: GET snapshot, and POST requirements/qualification/resume preview or approve. `get_readiness_service()` constructs local knowledge/document dependencies without an AI registry, so even invalid external-AI configuration does not block deterministic review. Static 409 covers unavailable/changed/corrupt evidence, 503 unavailable encryption, and 422 mismatched identity/invalid requests. No source text or secret appears in error details.

`job-readiness-ipc.ts` validates exact plain-object keys, IDs, bounded lists, enums, booleans and distinct values. Approval is a separate native cancel-default dialog displaying application, fingerprint, eligibility choice or selected immutable version. Only the main process supplies the fixed confirmation phrase. Backend recomputation still rejects changes during approval.

`JobReadinessPanel` is tied to the selected application/profile and explicitly loads evidence. It shows escaped source text, per-line classification, locked claims, per-requirement findings, coverage, separate eligibility approval and exact resume recommendation/version. Generation and immediate active guards suppress stale responses/duplicate actions. Changing selection/backend state clears review; unsaved requirements or findings disable downstream actions. Failed approval clears cached authority and requires reload; a queue-refresh failure preserves a confirmed saved decision.

## Validation and remaining work

Tests cover source identity and exact repeated-line spans, missing/all-preferred/ambiguous criteria, mandatory contradictions/unknowns, profile ownership, locked/permitted/superseded claims, corrupt historical document evidence, invalid Unicode, changed metadata/bytes/extraction, stale previews, atomic rollback, concurrency/idempotency, migration preservation and generic-selection bypass. IPC/UI tests cover native cancellation, unsafe objects, stale responses, changed application/profile, unsaved edits and truthful saved/failed outcomes.

The offline packaged probe checks that the frozen readiness router rejects a synthetic simulator workflow: snapshot is UNSUPPORTED with no allowed actions or source, requirements preview returns 409, and the exact unsupported state survives backup/restore. Full positive readiness uses sanitized source fixtures in backend/UI tests; no fake public-source authority or live employer request is introduced into the packaged probe.

Saved-source revisions, employer clarification, automated evidence suggestions, named-portal navigation/custom widgets/upload/recovery and independently verified submissions remain separate work. Current coverage is operator-reviewed evidence completeness, not hiring probability. Exact combined test counts, package hashes, protected integration and signed/live/physical acceptance are recorded separately.

