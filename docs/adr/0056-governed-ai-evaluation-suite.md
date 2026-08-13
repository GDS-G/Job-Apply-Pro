# ADR 0056: Governed AI evaluation suite

## Status

Accepted for Governed AI Evaluation Suite `v0.47.0-alpha.1`.

## Context

The original agent evaluation harness checked only top-level required keys and exact values from one gateway call. It could not express nested expectations, prove cited evidence stayed inside a fixture allowlist, detect prohibited output fragments, or measure whether independent model runs produced the same structured result. Cache reuse could also make a repeat test appear stable without invoking the provider again.

## Decision

Evaluation cases can declare required and expected RFC 6901 JSON pointers, an evidence-list pointer plus allowed evidence IDs, forbidden output terms, and one to five repeat runs. Repeat evaluations bypass the gateway cache while preserving all routing, consent, privacy, schema, budget, timeout, retry, and audit controls.

The harness records invocation IDs and a SHA-256 fingerprint of canonical structured output. It reports instability when independent outputs differ. Forbidden terms are reported only by their case-local ordinal, never copied into the evaluation result.

## Consequences

- Sanitized fixtures can test nested grounding and evidence containment without bespoke test code.
- Repeat stability represents independent gateway executions rather than cache hits.
- Every repeat remains an audited invocation and can consume provider budget; the count is capped at five.
- Fingerprints permit comparison without retaining plaintext output in the evaluation report.
- Passing evaluation proves only the declared fixture assertions, not truth, fairness, live-provider approval, or production readiness.

## Alternatives rejected

- Comparing only top-level keys cannot express nested agent structures.
- Reusing cache during repeats does not evaluate independent provider behavior.
- Echoing a matched forbidden value into a failure report can leak the material the test was designed to detect.
