# ADR-0041: Exact radio option locators

- Status: Accepted
- Date: 2026-08-12
- Build: Verified Radio Group Execution `v0.32.0-alpha.1`

## Context

A radio group has a group label but each mutually exclusive option is a separate control. Executing against the group label is ambiguous and selecting by raw HTML value may rely on hidden implementation data that is not meaningful to the operator.

## Decision

Each observed radio option carries its bounded value, visible label, and an exact `LABEL` semantic locator derived from that same visible label. A reviewed answer may execute only when it exactly matches one option label, exactly one such option exists, and every current option locator equals its visible label. The browser uses `CHECK` and verifies `CHECKED_EQUALS=true` on that exact option locator.

Option locators are part of the typed browser contract but not the existing binding fingerprint. Execution therefore re-observes and validates them at action time in addition to recomputing the binding fingerprint over visible option labels. Missing, duplicate, case-variant, changed, or non-label locators fail closed.

## Consequences

- Radio execution is tied to what the user can see and review.
- Hidden values are not used to choose an option.
- Duplicate visible labels remain manual because they are ambiguous.
- Custom radio-like widgets still require explicit adapter contracts.
- The existing sensitive action redaction and no-final-submit boundaries remain unchanged.
