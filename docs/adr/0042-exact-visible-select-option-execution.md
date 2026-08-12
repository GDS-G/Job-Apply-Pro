# ADR-0042: Exact visible select option execution

- Status: Accepted
- Date: 2026-08-12
- Build: Verified Select Option Execution `v0.33.0-alpha.1`

## Context

A native select option has a user-visible label and a hidden HTML value. The prior approved-field path accepted either form and sent the hidden value to Playwright. That allowed a reviewed answer to depend on implementation data the operator could not meaningfully verify and used value-based postcondition evidence.

## Decision

Approved native select execution accepts only one case-sensitive, unique current visible option label. It emits the distinct `SELECT_LABEL` browser action, calls Playwright's label-based select operation, and verifies `SELECTED_LABEL_EQUALS` against the selected option's trimmed visible text. Hidden option values remain in bounded observations for diagnostics and lower-level compatibility, but never choose an approved application answer.

The existing challenge service retains the lower-level `SELECT`/`VALUE_EQUALS` contract because its reviewed challenge records may intentionally carry a portal-provided value. This ADR governs only `ApplicationFieldExecutionService` and does not silently change that separate boundary.

## Consequences

- Hidden values, case variants, unknown labels, and duplicate visible labels fail closed.
- Browser evidence distinguishes value-driven select actions from visible-label-driven approved application fields.
- Candidate-bearing label values remain covered by sensitive action redaction.
- Native confirmation, fresh binding validation, human-only controls, and no-final-submit rules are unchanged.
