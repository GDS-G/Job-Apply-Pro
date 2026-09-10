# ADR-0060: Media lifecycle hardening

## Status

Accepted for Media Lifecycle Hardening `v0.50.1-alpha.1`. Supplements ADR-0059; no database migration or public JSON schema change.

## Problem

The initial Gemini adapter registered uploaded files only after all metadata checks passed. A valid file name with a missing URI could therefore escape cleanup. Deletion failures also raised a generic provider error: the gateway retried or fell back, uploading again and potentially reporting success while an earlier file remained retained. Upload and deletion responses were buffered without the interaction response limit.

## Decision and code map

- `ai/providers.py:AIProviderMediaRetentionError` identifies unknown finalization/resource ownership or unconfirmed deletion. It is terminal for the current invocation, distinct from ordinary retryable provider failures.
- `GeminiProvider.complete()` validates the model before upload. Its `uploaded_names` list owns every syntactically valid returned name immediately, before URI, MIME, or state checks. `finally` tries every owned resource in reverse order; a failed deletion does not skip other resources.
- `_upload_media(..., uploaded_names)` streams start and finalization responses. Finalization transport, status, JSON, size, or missing-name failures are conservatively retention-uncertain because the remote server may already have accepted bytes. A known name with unusable metadata is deleted before ordinary failure propagates.
- `_validate_upload_url()` allows HTTPS on the fixed Google host and `/upload/v1beta/files`, without credentials, fragments, or a nonstandard port. The opaque session query is preserved and never logged. This narrow path policy must be revalidated against authorized live evidence before enablement.
- Uploaded metadata must be an object with a valid `files/{id}`, matching MIME, `state=ACTIVE`, and an exact HTTPS `/v1beta/{name}` URI without query, fragment, credentials, or a nonstandard port. Processing, failed, or unknown state is not inference-ready; this image-only patch cleans up and fails rather than polling.
- `_read_response_body()` enforces `_MAX_RESPONSE_BYTES` (5 MiB) with 64 KiB consumer chunks across the lifecycle; redirects remain disabled. This bounds accumulated application response bytes, not total process RSS or an aggregate wall-clock deadline. `_delete_media()` accepts an official endpoint's 404 as already absent.
- `services/ai.py:AIGatewayService.invoke()` catches retention uncertainty before its generic retry handler, exits both retry and model loops, records one `FAILED` invocation with error code `AIProviderMediaRetentionError`, and writes no response cache entry. `AIGatewayMediaRetentionError` maps through the existing unavailable-error handler to a sanitized HTTP 503. Media consent is checked again before cache lookup.

## Privacy and recovery limits

No media bytes, file URIs, API keys, upload URLs, or raw exception text are added to audit records. There is no persisted cleanup queue or cross-invocation quarantine in this patch. A process crash or lost finalization response can still leave remote media without a recoverable local identifier. An explicit new request can upload again; the error tells the operator to review provider retention first. Do not claim zero retention or automatic crash recovery.

Live media remains gated on provider configuration, approved privacy/retention settings, per-use consent, and sanitized real-provider acceptance evidence. This patch does not implement EXIF stripping, full image decoding, processing-state polling, or an aggregate upload/inference/cleanup deadline. Keep those gaps visible in future work.

Google documents the upload/use/delete operations and provider expiry in the [Files API guide](https://ai.google.dev/gemini-api/docs/files), and defines `ACTIVE` as inference-ready in the [file resource reference](https://ai.google.dev/api/files). Provider expiry is not evidence of immediate deletion.

## Verification

`backend/tests/test_gemini_media_lifecycle.py` exercises multiple uploads, malformed known/unknown metadata, invalid URLs, failed and oversized finalization, cleanup failure, 404, response streaming bounds, processing state, and invalid interaction envelopes. `backend/tests/test_ai_gateway.py` verifies terminal retry/fallback behavior, failed sanitized audit, no cache write, HTTP 503, and revoked media consent before cache reuse. Tests use synthetic bytes and mock HTTP transport only.

Dependency maintenance also refreshes vulnerable npm transitive packages with bounded overrides, Vitest, and Python httpx2/pypdf minimums. No audit exemptions or disabled security checks are introduced.
