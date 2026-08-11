# ADR-0003: Deterministic workflow state machine

- Status: Accepted
- Build: Foundation `v0.1.0-alpha.1`

## Context

Application automation must resume safely, prevent invalid transitions, and distinguish attempted submission from verified completion.

## Decision

Represent workflow state with a closed enum and an explicit allowed-transition graph. Validate every transition in deterministic service code. Persist an append-only event containing workflow id, prior state, next state, actor, cause, verification outcome, and timestamp.

AI output may propose an action but cannot directly mutate workflow state. `SUBMISSION_ATTEMPTED` can advance to `SUBMISSION_CONFIRMED` only when verification is recorded; otherwise the workflow moves to `SUBMISSION_UNCERTAIN` or a controlled failure state.

## Consequences

Adding a state requires coordinated backend, shared-contract, migration when applicable, test, and documentation changes. The explicit graph makes replay and audit behavior predictable.
