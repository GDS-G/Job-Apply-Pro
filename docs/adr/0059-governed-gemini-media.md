# ADR 0059: Governed Gemini media

## Status

Accepted for Governed Gemini Media `v0.50.0-alpha.1`.

## Context

Complex resume and portal graphics can require model-assisted review, but user-supplied remote image URLs create server-side request risks and inline or persistent uploads can silently broaden data disclosure. Gemini's current Interactions API supports multimodal blocks and its Files API retains uploads for up to 48 hours unless they are deleted.

## Decision

Add `media` input parts for JPEG, PNG, and WebP bytes only. Validate declared MIME type against file signatures, cap each image at 5 MiB, cap requests at four images, serialize bytes as URL-safe base64 at the authenticated local API boundary, and require both ordinary external-AI consent and a separate `media_upload_consent` decision.

Requests containing media require a model route with `MULTIMODAL` capability. The Gemini adapter uses the official resumable Files API: start an upload, accept only an exact HTTPS Google upload-session URL, upload bytes without redirects, validate the returned file name, MIME type, and Google URI, pass the file URI to a stateless interaction, and delete each uploaded file immediately in a `finally` boundary. A deletion failure fails the whole invocation rather than claiming that cleanup succeeded. User-supplied remote image URLs remain rejected by Gemini.

Input and cache identities include media SHA-256, byte count, MIME type, and bounded display name but never retain media bytes. External consent is checked before either provider execution or encrypted cache reuse. Existing classification blocks, prompt, routing, timeout, retry, schema, tool, cost, encrypted cache, and sanitized audit controls remain in force.

## Consequences

- Governed visual review has a production-shaped source path without hidden provider retention.
- Media cannot route through a text-only model.
- Arbitrary remote media fetches and upload-host redirects are rejected.
- Files API deletion is attempted on success and failure; provider/network interruption can still leave a file subject to Gemini's provider retention policy, so live use requires reviewed provider terms and privacy settings.
- Model-extracted visual facts remain proposals requiring evidence review, never automatically verified candidate claims.

## Alternatives rejected

- Passing user-supplied URLs would create SSRF, authorization, and mutable-content risks.
- Leaving files for provider auto-expiry unnecessarily extends retention.
- Logging base64 or including it in cache identities would retain sensitive visual data.
- Inline image data avoids provider file retention but produces large JSON requests and does not provide a uniform explicit cleanup boundary.
