# ADR 0013: AI privacy, prompts, validation, and caching

- Status: Accepted
- Date: 2026-08-05
- Build: AI Gateway `v0.6.0-alpha.1`

## Context

Candidate and portal data is untrusted and may be sensitive. Model output is probabilistic, while repeated requests can be expensive. The gateway must protect privacy and make outputs reproducible enough to inspect and evaluate.

## Decision

Every request declares task, prompt/schema version, profile/source version, data classification, consent, budget, timeout, and cache policy. External calls require consent. Highly Sensitive and Restricted data are blocked from external providers; lower classifications are redacted where practical. User and portal inputs are serialized inside an explicit untrusted-data region separate from system policy.

Prompts are versioned, task-specific, minimal, and declare allowed tools, decision rules, output schema, and stopping conditions. JSON output and tool arguments are validated before persistence or use. Undeclared tools fail closed. Locked candidate facts remain higher authority than all model output.

Cache keys include profile, source, model, prompt, schema, privacy, task, input hash material, and output schema. Cache values use context-bound AES-256-GCM encryption. Invocation records store hashes and operational metadata, not prompt/input/output plaintext or provider credentials.

## Consequences

- Sensitive model use is explicit and auditable without logging candidate content.
- Invalid output can be retried, repaired, or routed to a fallback, but never silently accepted.
- Prompt/schema changes invalidate incompatible cache entries.
- Fine-tuning is unnecessary for the MVP; reviewed facts stay in structured retrieval rather than model weights.
