# ADR-0030: Encrypted calendar interview awareness

- Status: Accepted
- Date: 2026-08-11
- Build: Calendar Interview Awareness `v0.21.0-alpha.1`

## Context

The desktop notification layer could identify interview-request messages, but it had no durable source for confirmed upcoming calendar events. Calling Google or Microsoft every 60 seconds from the notification manager would create unnecessary provider traffic, couple reminder availability to the network, and enlarge the privacy and failure surface. Provider push subscriptions and webhooks require lifecycle, callback, verification, delivery, and policy infrastructure that this local-only alpha does not yet own.

Google Calendar `events.list` supports RFC 3339 `timeMin` and `timeMax`, recurring-instance expansion with `singleEvents`, deleted-event exclusion with `showDeleted=false`, and bounded page tokens. Microsoft Graph `calendarView` requires ISO 8601 `startDateTime` and `endDateTime`, expands recurring occurrences in the requested range, supports pages up to 1,000 items, and marks cancelled events through event state. The implementation follows those current official contracts:

- https://developers.google.com/calendar/api/v3/reference/events/list
- https://learn.microsoft.com/graph/api/calendar-list-calendarview?view=graph-rest-1.0

## Decision

Calendar synchronization is authenticated and explicitly owner-initiated. Each run reads the provider's primary/default calendar from one day before the anchor time through 60 days after it. Existing ten-page, 1,000-item, five-megabyte response, continuation-origin, and timeout limits remain in force. Google reads expand recurring events and omit deleted events. Outlook reads omit `isCancelled=true` events. Date-only Google events normalize at local-calendar midnight instead of invalidating the entire response.

Migration `20260811_0015` adds `provider_calendar_events`. Provider, an account-binding fingerprint, start, end, and synchronization timestamps remain queryable metadata so the local service can perform bounded window, account, and retention operations. Event identifiers, titles, attendees, conferencing URLs, locations, and complete event payloads are AES-256-GCM encrypted with provider-and-event-bound encryption context. The database maintains one row per provider/event identifier, overwrites the binding on a successful refresh, and returns rows only when the current credential reference and account hint reproduce that binding. Disconnecting or switching accounts therefore hides the prior account snapshot immediately, before another provider read occurs.

Every successful read replaces that provider's prior local snapshot: returned identifiers are inserted or updated and absent identifiers are removed. No reconciliation is committed if provider listing or model validation fails. The authenticated sync response returns only provider, counts, window bounds, and synchronization time. It never returns event identifiers or content.

Electron's notification refresh reads the authenticated local snapshot alongside existing local records. A bounded title classifier recognizes explicit interview, screen, recruiter-call, and hiring-manager signals. Events starting within 24 hours create a generic reminder; the identifier changes at the one-hour threshold so a closer reminder can be delivered once. Started events and events beyond 24 hours do not alert. Native and in-app wording excludes provider, employer, role, title, attendees, location, URLs, and account details.

## Consequences

- Reminder refreshes are network-independent after a successful manual sync and do not generate background provider requests.
- Removed and cancelled events disappear on the next successful full-window sync; they are not real-time until the owner syncs again.
- Calendar details are available only through the authenticated loopback API and remain protected local data.
- No webhook, push-subscription, production-provider approval, or live-provider compatibility claim is made.
- Owner-registered OAuth clients, reviewed least-privilege scopes, owner-controlled browser authorization, quota/terms approval, and authorized live evidence remain external gates.
