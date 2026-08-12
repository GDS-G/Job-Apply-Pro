# ADR-0029: Encrypt incremental provider synchronization state

- Status: Accepted
- Date: 2026-08-11
- Build: Incremental Provider Sync `v0.20.0-alpha.1`

## Context

Mail synchronization previously repeated a bounded recent-message listing on every request. Provider/message deduplication protected local records, but it did not reduce provider reads or retain the providers' official change-tracking state. Gmail exposes mailbox history IDs and Microsoft Graph exposes folder-scoped delta links. Both are opaque provider state, can expire, and must not be exposed to the renderer, logs, documentation, or diagnostics. Advancing state before all imported messages are durable could permanently skip a message after a local failure. Reusing state after a different account is authorized could also apply one mailbox's cursor to another.

## Decision

Persist one synchronization row per mail provider. The cursor and an account-binding fingerprint are stored together inside the existing AES-256-GCM envelope; the table contains no plaintext cursor. The binding fingerprint covers provider, OAuth credential reference, and provider account hint. A new authorization reference or account hint therefore starts a new initial synchronization, while the obsolete encrypted value is replaced only after a successful operation.

Gmail initial and recovery synchronization first reads the mailbox profile's current `historyId`, then performs the existing bounded full message listing. Capturing the history ID before listing ensures a message that arrives during the full read is replayed by the next partial synchronization instead of being skipped. Later operations call `users.history.list` with that ID and `messageAdded`, follow at most ten pages, deduplicate at most 1,000 message identifiers, fetch each message through the existing bounded MIME path, and store the final returned history ID. Gmail HTTP 404 for an expired history ID triggers one bounded recovery full synchronization.

Outlook synchronizes the well-known Inbox folder with Microsoft Graph message delta and `changeType=created`. It follows only HTTPS links on the exact `graph.microsoft.com` host, default TLS port, and fixed Inbox delta path. The complete final `@odata.deltaLink` is encrypted rather than parsed or reconstructed. A 410 response or `syncStateNotFound` error triggers one bounded recovery enumeration. Removed or update-only entries without a complete received message are ignored because local communication records are immutable evidence and this slice imports new mail rather than mirroring an entire mailbox.

The service analyzes and saves every returned message before persisting the new cursor. If provider parsing, account validation, classification, encryption, or persistence fails, the prior cursor remains authoritative and a retry may safely replay already-imported provider IDs through the existing unique constraint. API and Electron contracts expose only provider, sync mode (`INITIAL`, `INCREMENTAL`, or `RECOVERY`), fetched/imported/duplicate counts, local record IDs, and cursor update time. Cursor values never cross the authenticated backend boundary.

## Consequences

- Routine synchronization reads provider changes instead of repeatedly enumerating the same recent mailbox window.
- Crashes and partial failures favor replay over data loss; provider/message uniqueness makes replay idempotent.
- Cursor expiry is recoverable but can temporarily require another bounded full synchronization.
- Outlook synchronization is explicitly Inbox-scoped. Other folders require separately keyed state and evidence in a later change.
- Webhooks and push notifications remain unimplemented. Gmail watch/Pub/Sub and Microsoft change-notification endpoints require owner-controlled cloud callback infrastructure, registration, terms, and operational ownership; local pull-based incremental synchronization does not claim them.
- Live OAuth authorization, provider quotas, terms approval, and authorized health evidence remain external release gates.

## Provider references

- [Synchronize clients with Gmail](https://developers.google.com/workspace/gmail/api/guides/sync)
- [Gmail users.history.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list)
- [Gmail users.getProfile](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile)
- [Microsoft Graph message delta](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0)
- [Microsoft Graph synchronization reset guidance](https://learn.microsoft.com/en-us/graph/delta-query-overview)
