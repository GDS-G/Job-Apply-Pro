# ADR-0031: Native Gemini secondary provider

- Status: Accepted
- Build: Native Gemini Fallback `v0.22.0-alpha.1`

## Context

Phase 6 requires at least one secondary cloud adapter that is meaningfully independent of the primary provider. The earlier `SECONDARY_COMPATIBLE` kind reused the OpenAI-compatible `chat/completions` and embeddings wire contract, so it supplied configurable routing but did not prove a separate provider integration. Current Google documentation recommends the Gemini Interactions API for new work and retains a dedicated batch-embedding endpoint.

## Decision

Add a native `GEMINI` provider kind and adapter. Text requests use the Gemini Interactions API with `store=false`, separate system instructions, text input blocks, client-side function tools, structured JSON response formats, and provider usage totals. Embeddings use `models/{model}:batchEmbedContents` and preserve input order. Existing gateway policies continue to own classification, explicit external consent, redaction, model capability selection, cost budgets, bounded retries, schema validation, tool allowlists and argument validation, encrypted caching, and sanitized audit records.

The adapter accepts only `https://generativelanguage.googleapis.com/v1beta` on the default TLS port, pins the documented `2026-05-20` Interactions API revision, places the API key only in `x-goog-api-key`, disables redirects, validates model resource names, bounds responses to 5 MiB, requires finite same-dimension embeddings, and removes provider error bodies from surfaced failures. It rejects remote image URLs because Gemini media calls require a trusted upload/URI plus a verified MIME type; that separate ingestion and retention boundary is not silently inferred from an arbitrary URL.

## Consequences

- OpenAI-compatible, native Gemini, and loopback llama.cpp routes can now fail over across independent wire protocols.
- The prior `SECONDARY_COMPATIBLE` kind remains for backward-compatible OpenAI-style alternatives, but no longer counts as the distinct native secondary integration.
- Operators must supply the Gemini API key only through local secret configuration, explicitly consent to external processing, and review provider terms, privacy, retention, quota, and data-region controls before live use.
- Sanitized `MockTransport` fixtures validate the contract. No test account, pasted password, production API key, live availability, quota, or privacy-policy approval is embedded or claimed.
