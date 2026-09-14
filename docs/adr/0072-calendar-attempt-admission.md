# ADR-0072: Calendar attempt admission

## Status and scope

Accepted as the source design for Calendar Attempt Admission `v0.62.0-alpha.1`.
This release permits one explicitly reviewed calendar **create** attempt only after
the plan is bound to the selected provider account and connection. It does not
enable calendar updates, recurring events, conferencing creation, invitations,
provider-default reminders, automatic retry, provider delivery claims, or unattended scheduling. Provider
capabilities and production automation remain disabled until their separate live
and release gates are satisfied.

The purpose of this milestone is not to broaden calendar behavior. It closes the
unsafe window in which a caller could repeat an old plan or retry an ambiguous
external write without a durable pre-dispatch reservation.

## Reviewed plan contract

The backend, not the renderer, creates the immutable plan and owns its identifier,
binding values, fingerprint, and attempt key. A current plan records:

- policy and provider-wire contract versions;
- provider, stable account identity hash, reviewable account label, exact OAuth
  credential epoch/binding fingerprint, and primary-calendar target;
- CREATE-only event title, offset-aware start/end, IANA time zone, optional plain
  location, an empty attendee list, invitation/reminder policies `NONE`, visibility
  `PRIVATE`, and availability `BUSY`;
- provider-native idempotency policy; and
- an optional workflow reference that must identify an existing application.

Unknown fields are rejected. Start must precede end and both instants must agree
with the reviewed time-zone rules. Control characters, invalid zones, caller-owned
provider identifiers, attendee values, conference links, recurrence and unsupported
provider options are rejected before a plan or attempt is stored. Sensitive plan
content and binding evidence remain authenticated ciphertext at rest. The private
connection fingerprint does not cross the API or renderer boundary.

The plan fingerprint includes its identifier, provider, workflow, exact event,
policy/wire versions, account binding, calendar target and idempotency policy. The
service recomputes it after decrypting the plan and revalidates the live provider
binding immediately before claiming an attempt. A changed account, credential
epoch, permission, scope, adapter or plan requires a fresh review.

## Durable one-attempt claim

Migration `20260913_0028` adds `calendar_mutation_claims`, keyed by `plan_id` with
a unique `audit_id`. Both columns have foreign keys to the immutable plan and the
communication mutation audit. Upgrade backfills only matching calendar provider,
kind and resource relationships, choosing the stable oldest `(occurred_at, id)`
audit. Downgrade is refused when any calendar mutation plan exists: the previous
release cannot safely parse the expanded encrypted event shape, even when a modern
plan has not yet acquired a claim.

Execution first resolves a same-key replay through the exact
claim → audit → plan relationship. A different idempotency key, fingerprint,
resource, provider or kind conflicts. With no existing claim, one transaction
inserts the `PLANNED` audit and unique claim before any token lookup or provider
transport. Concurrent losers read and verify the winning relationship; they do not
dispatch. A recovered `PLANNED` audit means the external outcome is unknown and
requires reconciliation—it is never an automatic retry.

Terminalization is a compare-and-set transition from that exact `PLANNED` audit.
Terminal rows and claims are immutable. Provider acceptance with a bounded,
validated provider resource identifier records `CONFIRMED`. This means only that
the provider accepted the create and returned an identifier; it does not prove
invitation delivery, readback, attendance or later provider state. Only a typed
pre-dispatch or definitely-not-applied refusal may record `FAILED`. Transport,
timeout, malformed/oversize/compressed response, unexpected exception, invalid
identifier, or loss of the terminal database write records or leaves an
`UNCERTAIN`/`PLANNED` consumed attempt and must not be retried automatically.

Google Calendar receives a deterministic provider-valid event identifier derived
from the claimed attempt, explicit private/opaque visibility and no default
reminders. Microsoft Graph receives a deterministic UUID `transactionId`, local
wall times paired with the reviewed zone, private sensitivity, busy availability,
no reminder and no response request.
These are provider defenses against accidental duplicate creates, not permission to
blindly replay an ambiguous call. Redirects and injected authentication challenge
replays are disabled, responses are streamed under byte/time bounds, and response
or token details are never returned in audit errors.

## Native review boundary

The renderer may request a plan only while the exact calendar write capability is
configured and connected. The main process creates the actor and idempotency key.
Before execute, it refetches the exact plan and presents a native confirmation that
names the provider, account, primary calendar, title, start/end, zone, location and
the fixed private, busy, no-reminders, no-invitations policy. The cancel/default
action performs no write. Acceptance is rejected if the fetched plan, capability or
account binding no longer matches the reviewed values.

Duplicate clicks, renderer reconnects, IPC concurrency and backend restarts replay
the existing claimed result and never allocate a second key for that plan. A
`PLANNED`, `FAILED` or `UNCERTAIN` attempt remains consumed and is shown as requiring
review or reconciliation. The renderer receives no OAuth token, credential
reference, arbitrary network capability or raw provider response.

## Restore and release boundaries

The compiled forward-history policy advances to schema `20260913_0028` and treats
`calendar_mutation_claims` as protected history. A claim must point to the oldest
matching calendar audit for the same plan, provider, kind and fingerprint. Exact
physical columns, primary key, uniqueness and foreign keys are checked. A staged
restore that loses, changes or fabricates a claim or its plan/audit relationship is
rejected by both staged and final serialized-history gates. Legacy schema `0027`
remains admissible only when it contains no claim-table history.

Automated fixtures validate plan admission, account/credential pinning, provider
wire contracts, concurrent claiming, replay, crash and terminal outcomes, migration
upgrade/downgrade, native confirmation/IPC, and backup-before-attempt preservation.
Those tests are source and packaged-candidate evidence only. Authorized provider
registration, legal/terms approval, owner-controlled OAuth/MFA, sanitized live
acceptance, Authenticode signing, two-version update/rollback and physical Windows
validation remain external release requirements.
