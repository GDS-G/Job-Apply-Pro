# ADR 0044: Privacy-bounded native constraint validity

## Status

Accepted for Constraint-Aware Form Readiness `v0.35.0-alpha.1`.

## Context

The required-field coverage review can identify bindings and verified app actions, but a user may complete a field manually. Observations intentionally omit current values, so the review cannot otherwise distinguish an empty required native control from one the browser currently accepts. Reading values or provider validation messages would unnecessarily expose candidate data.

## Decision

Add two booleans to each bounded observed control: whether the element participates in native constraint validation and whether its current native validity state is satisfied. The Playwright worker reads `willValidate` and `validity.valid`; it does not invoke mutating behavior, return the value, or return validation messages.

Required-field coverage classifies a supported, non-legal, enabled, locatable control as `SATISFIED_ON_PAGE` when both booleans are true. This classification precedes binding readiness because the current page does not need another automated fill to satisfy its native constraint. It may include one unambiguous current binding ID for navigation, but grants no execution authority.

## Consequences

The checklist reflects manual and automated completion without retaining candidate values. Native validity proves only HTML constraint satisfaction at observation time. It does not prove the value is truthful, semantically correct, equal to an approved answer, accepted by provider-side validation, or submitted. Custom controls and controls without native validation continue through existing manual, binding, and execution classifications.
