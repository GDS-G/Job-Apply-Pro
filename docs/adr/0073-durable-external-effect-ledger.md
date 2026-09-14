# ADR-0073: Durable external-effect ledger

## Status and scope

Accepted as the source design for Durable External-Effect Ledger
`v0.63.0-alpha.1`.

This milestone closes the unjournaled crash window for browser mutations and
cost-bearing AI completion and embedding calls. It does not enable unattended
portal submission, calendar UPDATE, provider delivery claims, automatic retry of
an ambiguous call, or any production portal/provider capability that remains
disabled by policy.

## Decision

Every covered call receives one privacy-safe logical effect key and one keyed
request fingerprint before provider or browser dispatch. Migration
`20260913_0029` stores an operation and its ordered attempts in
`external_effect_operations` and `external_effect_attempts`.

The state machine is:

1. `PREPARED` commits the logical claim and attempt before external I/O.
2. `DISPATCHING` commits before entering the worker or provider adapter.
3. `CONFIRMED` records a validated provider/browser response and a safe local
   evidence reference.
4. `FAILED` is permitted only for an outcome known not to require ambiguity
   recovery.
5. `UNCERTAIN` consumes the logical effect whenever dispatch may have occurred
   but the result cannot be proved.

Terminal outcomes are immutable. A continued provider route may follow only a
known failed attempt or a complete but invalid response; uncertainty always stops
retry and fallback. An exact replay joins the existing operation and is refused as
consumed rather than dispatching again. A different request under the same key is
a conflict.

Claim and request fingerprints are keyed, not plaintext request hashes. Stored
rows contain only bounded identifiers, safe error codes, counts, costs and result
references. Prompts, candidate data, media, browser page content, raw exceptions,
provider responses, tokens and credentials are never written to the ledger.

## Browser boundary

Browser action keys are derived from the session and exact next sequence. The
browser action attempt identifier is also the `browser_actions` row identifier.
The runtime permits one worker attempt only; configured restart retry or backoff
is rejected.

The action row is committed before the effect is terminalized. A validated worker
postcondition records `CONFIRMED`. A typed not-applied result records `FAILED`.
Worker loss, timeout, malformed response, unexpected error or startup discovery
of a stranded `DISPATCHING` attempt records `UNCERTAIN`. The matching browser
session is fenced in `USER_TAKEOVER`; resume, restart and new automated actions
remain blocked until an operator reconciles the outcome.

## AI boundary

Completion and embedding requests derive deterministic effect subjects from the
task, prompt/schema versions, privacy classification, input/media fingerprints,
route, consent, cost/timeout policy and tool/schema fingerprints. API callers may
provide a new bounded effect key only when they intentionally authorize a new
logical call. Cache hits occur before admission and do not create provider
attempts.

Each provider call receives its own attempt. The attempt identifier is also the
`model_invocations` identifier for the terminal local audit row. Explicit
pre-dispatch rejection and complete invalid responses may move to another
configured route. Transport ambiguity, incomplete/oversize processing, unresolved
media retention, unexpected exceptions and local evidence persistence failure
become `UNCERTAIN` and stop all retries and fallback. Raw provider details are
reduced to static safe codes. Cache population is optional only after both the
provider result and local invocation evidence are durable.

## Recovery and schema compatibility

Startup recovery converts every stranded `DISPATCHING` operation/attempt to
`UNCERTAIN`; it never guesses that an effect was not applied. Downgrade to schema
0028 is refused while ledger history exists.

The compiled forward-restore policy advances to schema `20260913_0029` and 46
protected application tables. Both ledger tables are exact replay-authority sets,
roots for history admission, and are checked for exact columns, indexes, primary
and unique keys, foreign keys, compiled enums, bounded values, contiguous attempt
sequence, operation/attempt state agreement and confirmed local evidence.
Reserved `CALENDAR_UPDATE` records are refused because no production route owns
that kind yet. Empty schemas 0025–0028 remain eligible only through the existing
reviewed legacy compatibility path; recorded legacy history still requires a
post-upgrade complete backup.

## Consequences and remaining gates

The ledger prevents automatic duplicate side effects after common response-loss
and crash boundaries, but it cannot prove remote state by itself. An `UNCERTAIN`
outcome requires provider/browser reconciliation or explicit user takeover. Mail
send, calendar CREATE and Gemini media deletion retain their specialized journals;
they are not dual-written into this generic ledger.

Source and controlled Chromium/provider-fixture tests establish the state-machine,
privacy, fallback, recovery, migration and restore contracts. They do not replace
protected CI/security, signed installer/update/rollback evidence, physical Windows
failure injection, authorized live provider/portal validation, terms approval or
operator-controlled login/MFA.
