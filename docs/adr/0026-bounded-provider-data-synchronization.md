# ADR-0026: Bound provider data synchronization

- Status: Accepted
- Date: 2026-08-11
- Build: Provider Data Resilience `v0.17.0-alpha.1`

## Context

The Gmail, Microsoft Graph, Google Calendar, and Outlook Calendar adapters previously read only the first provider page. The official APIs expose opaque continuation state: Google returns `nextPageToken`, while Microsoft Graph returns a complete `@odata.nextLink`. Failing to continue loses records; following an arbitrary URL can disclose the OAuth bearer token; and unbounded pages, responses, MIME trees, attachment metadata, or message bodies can exhaust local resources. The mail adapters also had no authenticated application operation that imported connected-provider messages into the encrypted communication repository.

## Decision

Provider reads are bounded to ten pages, 1,000 collection items, 5,000,000 bytes per HTTP response, and 8,000 characters per continuation value. Google continuation tokens are supplied only as the next `pageToken` while the original query parameters remain unchanged. Microsoft continuation URLs must use HTTPS, the exact `graph.microsoft.com` host, the default or 443 port, no user information or fragment, and the exact expected v1.0 collection path. The client follows the complete opaque Microsoft URL and never constructs or edits its skip token. Repeated tokens or links, invalid collections, oversized responses, and exceeded limits fail closed.

Gmail message identifiers are deduplicated before detail reads. MIME traversal is iterative and limited to 500 parts; decoded bodies and encoded input are bounded. Attachment names are trimmed, deduplicated, limited to 100 entries and 500 characters each, and never treated as file content. Outlook requests attachment metadata only for messages whose `hasAttachments` flag is true, selects only `name`, `isInline`, and `size`, ignores inline resources, and never downloads attachment bytes.

An authenticated `POST /api/v1/communications/providers/{provider}/messages/sync` operation is the only new mail-read entry point. It accepts only Gmail or Outlook, invokes only a connected OAuth adapter, analyzes and encrypts messages through the existing communication service and repository, deduplicates on provider plus provider message ID, and returns provider, fetched/imported/duplicate counts, and local record IDs. Electron validates the provider at IPC, exposes sync only for connected read-enabled mail providers, and never receives OAuth tokens or attachment content.

## Consequences

Sanitized HTTP fixtures now exercise multi-page provider reads, full-next-link handling, attachment metadata pagination, duplicate suppression, repeated-token rejection, and off-origin next-link rejection. Live provider authorization, provider terms, quota policy, webhook/delta synchronization, and production health evidence remain external or future work. A sync result proves only that bounded metadata and message text were imported into local encrypted records; it is not evidence that a provider integration is production-approved.

## Provider contract references

- [Gmail users.messages.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)
- [Google Calendar events.list](https://developers.google.com/calendar/api/v3/reference/events/list)
- [Microsoft Graph list messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0)
- [Microsoft Graph list message attachments](https://learn.microsoft.com/en-us/graph/api/message-list-attachments?view=graph-rest-1.0)
- [Microsoft Graph list calendarView](https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview?view=graph-rest-1.0)
