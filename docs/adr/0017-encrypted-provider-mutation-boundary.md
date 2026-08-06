# ADR 0017: Encrypted provider and mutation boundary

- Status: Accepted
- Date: 2026-08-05
- Build: Communication & Scheduling `v0.10.0-alpha.1`

## Context

Email and calendar integration introduces OAuth tokens, recruiter content, candidate replies, interview details, attachments, and externally visible mutations. The renderer must not become a secret or network boundary, and an attempted write must never be represented as successful without provider evidence.

## Decision

Provider implementations conform to backend-owned message and calendar adapter protocols. Live adapters are disabled until an opaque credential reference can be resolved by an operating-system credential broker. Tokens and client secrets never cross renderer IPC and are never stored in application SQLite.

Normalized analyses, reply drafts, and calendar event snapshots are encrypted with the local AES-256-GCM master key and record-specific contexts. Searchable storage is limited to provider identifiers, category, workflow link, review status, timestamps, fingerprints, and mutation state.

Every send, event create, or event update requires a persisted resource fingerprint and unique idempotency key. The service writes a `PLANNED` audit before invoking the adapter, then records `CONFIRMED` only when the provider returns an immutable identifier; bounded provider failures become `FAILED`. Replaying an idempotency key returns its existing audit without repeating the external write.

Automatic-send policy is category-specific and disabled by default. Enabling it still uses the same planned mutation, system actor, idempotency, provider confirmation, and audit requirements. Attachment decisions bind an exact candidate profile and document version.

## Consequences

- Sanitized fixture adapters can validate normalization, mutation ordering, idempotency, and recovery without live accounts.
- Live Gmail, Outlook, Google Calendar, and Outlook Calendar support can be added behind stable contracts without changing feature services or renderer authority.
- Account authorization and provider-specific OAuth setup remain an explicit deployment step, not an implicit effect of installing or launching the application.
