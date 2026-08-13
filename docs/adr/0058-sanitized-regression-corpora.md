# ADR 0058: Sanitized regression corpora

## Status

Accepted for Sanitized Regression Corpora `v0.49.0-alpha.1`.

## Context

Individual deterministic tests cover AI evaluation assertions and document parser behaviors, but they do not provide one versioned, reviewable corpus that can grow without changing the execution contract. Using actual applicant files or portal-account data would create privacy, retention, and secret-handling risks.

## Decision

Store bounded JSON corpora with explicit schema and corpus versions. The AI corpus contains synthetic input plus schema-valid fixture output for all six governed agent roles; each case becomes an ordinary `EvaluationCase` and runs at least twice through the same gateway with cache bypass, output fingerprints, evidence allowlists, forbidden-term checks, routing, budgets, and invocation audit records.

The document corpus declares generated fixture kinds and exact expected media type, parser provenance, block text, block kinds, and warnings. Tests generate fixture bytes in memory and run them through the production extractors. No candidate file, account data, or downloaded third-party document is retained.

Corpus parsers fail closed on unknown fields, duplicate case IDs, malformed expectations, invalid/oversized JSON, credential-shaped fields, and email addresses. The only accepted classification is `SANITIZED_SYNTHETIC`.

## Consequences

- AI and document regression evidence is versioned and reviewable.
- Every AI agent role has deterministic repeat coverage without a live provider.
- Representative supported document layouts share one exact expectation contract.
- Corpus success is source evidence only; it does not establish model truth, fairness, live-provider permission, real-world layout completeness, or production readiness.

## Alternatives rejected

- Real resumes or copied production outputs would expose candidate data and create unclear consent and retention obligations.
- Unvalidated ad hoc JSON could silently drift or embed sensitive material.
- A separate mock-only execution path could pass while the production gateway or extractor regressed.
