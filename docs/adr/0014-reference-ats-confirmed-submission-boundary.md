# ADR 0014: Reference ATS confirmed-submission boundary

- Status: Accepted
- Date: 2026-08-05
- Build: Portal Vertical Slice `v0.7.0-alpha.1`

## Context

Phase 7 requires one complete portal workflow through confirmed submission. Enabling a real portal while adapter contracts, confirmation evidence, recovery, and policy enforcement are still evolving would create unacceptable account and application risk. A test-only path must still exercise the production-shaped browser, persistence, workflow, and desktop boundaries.

## Decision

The first adapter is a deterministic reference ATS restricted to loopback origins. Its discovery endpoint returns strictly validated job records. Browser-observed job identity must match discovery before the application proceeds. The workflow persists deduplication, requirements, deterministic evidence-backed fit, document choice, canonical field mappings, verified actions, checkpoints, and screenshots.

Imported originals remain encrypted. The browser runtime decrypts only the selected document into a session-scoped staging directory, verifies the upload, and deletes the plaintext immediately. Stop cleanup repeats deletion defensively.

Preparation stops at `READY_TO_SUBMIT` and persists the review-page fingerprint. Submission requires a second authenticated desktop action carrying that exact fingerprint and the explicit phrase `SUBMIT REFERENCE APPLICATION`. The click transitions only to `SUBMISSION_ATTEMPTED`. `SUBMISSION_CONFIRMED` requires both a supported confirmation page and a parsed confirmation code; missing evidence transitions to `SUBMISSION_UNCERTAIN`.

## Consequences

- The complete workflow can be repeated on Windows and in CI without contacting a production portal.
- A button click, URL change, or model claim alone cannot confirm submission.
- Portal adapters share a typed capability and evidence vocabulary before Phase 9 expansion.
- Production portal automation remains disabled until a later accepted decision defines credentials, live-site policy, rollout, and monitoring.
