# ADR-0068: Greenhouse public discovery

## Status and scope

Accepted for Greenhouse Public Discovery `v0.58.0-alpha.1`. Exact-version local integrated and unsigned-package checks pass; protected integration is tracked separately. This manually initiated public-read and local-import slice does not log in, open a browser, transmit candidate data, score qualifications, choose documents, upload, submit, or enable production portal automation.

The official [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html) documents unauthenticated public GET endpoints and distinct posting identifiers. Submission is a separate authenticated endpoint. This release implements only public reads; public API availability is not permission for automated applications or evidence of live acceptance.

## Contracts and identity

`domain/job_discovery.py` defines frozen strict, extra-forbidden `GreenhouseBoardRequest`, `GreenhouseReviewRequest` and `GreenhouseImportRequest`. `board_token` is one to 100 ASCII letters/digits/underscore/hyphen, begins with a letter/digit, and cannot case-insensitively equal `internal`. It is a token, not a URL or credential. `posting_id` is a positive decimal string bounded by 9,223,372,036,854,775,807; strings and main-process `BigInt` validation avoid JavaScript precision loss. Import also requires a 64-character lowercase SHA-256 review fingerprint and an existing local profile ID.

`GreenhouseJobList` includes board token/name, fetch time, up to 1,000 summaries and excluded-prospect count. Summaries contain posting ID, title, optional location, recognized canonical source URL and navigation-supported flag. `GreenhouseJobReview` adds employer, normalized description, fixed API URL, reported URL, optional provider update timestamp, normalizer version and fingerprint. `qualification_status` is literally `NOT_EVALUATED`; missing requirements cannot produce a perfect score.

## Transport and resource bounds

`portals/greenhouse.py:GreenhousePublicBoardClient.list_jobs()` reads board metadata and jobs; `review_job()` reads one selected posting. `_get()` constructs only fixed `https://boards-api.greenhouse.io` paths, disables redirects and environment proxy/credential inheritance, retains TLS verification and sends no authorization, cookies, local profile IDs or candidate fields. Responses must be JSON with identity encoding; URLs returned in content never become fetch targets.

Bounds are 65,536 metadata bytes, 2 MiB list bytes, 512 KiB detail bytes, 1,000 jobs, 250,000 input HTML characters and 50,000 normalized description characters. Each list/review shares a 20-second monotonic budget across reads and validation. After client entry, the remaining time is checked again before dispatch; network phases receive at most five seconds and remaining time, with pool time at most one second. Every unchunked response yield and final validation checks the deadline. These are cooperative checks, not hard OS/transport cancellation.

404/410 means source unavailable. Other non-200 statuses, invalid content type/encoding, malformed/deep JSON, duplicate JSON keys, non-finite constants, null/surrogate Unicode, conflicting duplicate IDs or inconsistent list totals fail with static input-free errors. Identical duplicate jobs collapse. Null `internal_job_id` entries are excluded prospect posts; internal job IDs never replace posting IDs.

## Source normalization and fingerprints

`description_text()` performs at most two entity-unescape passes and passes the result through `_DescriptionParser`. Block separators preserve readable text boundaries; script, style, template, iframe, object, SVG and noscript content is suppressed. Hidden nesting and accumulated text are bounded. React displays escaped text in a `pre` element, without HTML execution, AI interpretation or external resources. This is a bounded review representation, not exact page layout or proof of an employer requirement.

`_posting_url()` requires HTTPS metadata without credentials, fragments, controls, backslashes or a non-default port. Recognized destinations are exactly `boards.greenhouse.io` or `job-boards.greenhouse.io` and `/<board>/jobs/<posting>`. Only one `gh_src` query value is permitted and removed from the canonical URL. Other employer hosts remain metadata-only (`source_url = None`); a supplied `gh_jid` must match. This panel opens no browser even for recognized URLs.

`NORMALIZER_VERSION = greenhouse-text-v1`. The fingerprint hashes sorted compact canonical JSON of all normalized source fields: identities, employer/title/location, description, API/reported/canonical URLs, provider update time, normalizer and qualification literal. Local fetch time and the fingerprint itself are excluded. A URL or timestamp change can invalidate review even when description text is unchanged.

## Atomic local import

`GreenhouseDiscoveryService.import_job()` verifies the local profile first, constructs a public-only review request and refetches the posting. The profile never enters provider arguments. A vanished source returns `SOURCE_UNAVAILABLE`; disagreement with the operator-reviewed fingerprint returns `STALE_REVIEW` before writes.

`GreenhouseDiscoveryRepository.import_reviewed()` commits job, immutable snapshot, application and truthful initial event in one transaction, without generic individually committing add methods. Job identity is `(source = greenhouse-public, external_id = <board>:<posting>)`. A deterministic UUID5 workflow ID also binds the local profile. Unique conflicts roll back and retry once; other storage failures roll back and return a static conflict.

Migration `20260913_0025`, after `20260913_0024`, adds `job_discovery_snapshots`: job ID primary/foreign key, review fingerprint, normalized review JSON and creation timestamp. This is public source data, not encrypted candidate evidence. The backup schema revision advances accordingly. Tests preserve earlier jobs/applications and cover rerun and downgrade/re-upgrade; development downgrade is not a supported active-workspace recovery method.

New applications start `DEDUPLICATED`, without a selected document. Their first event records reviewed local saving, not qualification, application opening or submission. Repeating the same source/profile returns `EXISTING` without duplicate records/events. A different profile can create its own workflow for the same unchanged source. A current source differing from a previously saved snapshot returns `SOURCE_CHANGED` and preserves history; saved-source refresh is not implemented here.

## API, IPC and desktop flow

Authenticated local POST routes are `/api/v1/discovery/greenhouse/list`, `/review` and `/import`; provider traffic remains GET. Domain errors map to static 502, profile/storage conflict to static 409, and invalid input to the existing sanitized 422 policy. Listing and preview do not mutate candidate workflows.

`greenhouse-discovery-ipc.ts:registerGreenhouseDiscoveryIpc()` accepts one plain object with exact own keys, validates board/posting/fingerprint/profile values, and calls the private backend client. Preload exposes only typed operations, never arbitrary URLs. Failed import tells the operator to refresh local workflows; it does not imply an external application was submitted.

`GreenhouseDiscoveryPanel` requires explicit list, selected-review and import actions. Generation tokens and an immediate active ref suppress stale responses and duplicate clicks. Board, posting, profile or backend changes invalidate review. Success updates the queue; queue-refresh failure preserves the saved result. `SOURCE_CHANGED` is latched per source for the panel session, so rereview cannot offer unsupported replacement. No automatic polling or background discovery is added.

## Truthful workflow controls

`WorkflowRunSnapshot.allowed_controls` is backend-derived. `allowed_workbench_controls()` returns simulator controls only for `workbench-mock`; real imported records receive none. Workbench control rechecks permissions server-side, so mock advancement cannot make a public import appear qualified or applied.

Independent review found a second path: the generic authenticated transition endpoint could append caller-fabricated success events to real import history. `WorkflowService.transition_public()` now requires a persisted synthetic application at the claimed current state. Internal verified service transitions remain separate. Tests reject fabricated qualification/confirmation events for imported, other non-synthetic and unknown workflows.

## Validation and remaining scope

Sanitized client fixtures cover fixed GETs, identifiers, bounds, prospect exclusion, metadata, plain-text extraction, malicious URLs/redirects/encoding/JSON, client-setup time, trickled bodies and validation deadlines. Repository/API tests cover profile separation, concurrent/idempotent import, changed/unavailable sources, atomic rollback, immutable snapshots, migration preservation and fabricated transitions. Desktop tests cover strict IPC, escaped rendering, stale responses, profile changes, duplicate clicks and truthful outcomes. No live board is used by these tests.

Exact-version combined tests, unsigned package probes, hashes and protected GitHub evidence belong in the readiness audit. Saved-source revision review, explicit requirement/evidence/eligibility review, review-bound document selection and provider-specific navigation/application/upload/recovery remain separate work. Generic replay or public import is not a complete named-portal adapter; authorized live and signed/physical release acceptance remain distinct gates.
