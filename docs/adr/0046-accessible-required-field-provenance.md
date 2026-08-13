# ADR 0046: Accessible required-field provenance

## Status

Accepted for Accessible Required Field Review `v0.37.0-alpha.1`.

## Context

Modern portals may declare a visible field required through `aria-required=true` without using the native HTML `required` attribute. Ignoring that signal omits user-visible required work from the checklist. Treating the two signals as identical is also unsafe: an ARIA-only text input commonly reports `willValidate=true` and `validity.valid=true` because the browser has no native missing-value constraint, which could incorrectly classify an empty field as satisfied.

## Decision

Observed controls retain one combined `required` boolean for downstream compatibility and add two provenance booleans: `native_required` and `accessible_required`. The worker treats `aria-required` value `true` case-insensitively and does not infer required state from visible text or arbitrary CSS.

Required-field coverage includes a visible control when the combined signal is true. `SATISFIED_ON_PAGE` additionally requires `native_required=true`, `will_validate=true`, and `constraint_satisfied=true`. An accessibility-only required control therefore continues through manual, unbound, stale, ambiguous, ready, or verified classification until explicit evidence resolves it; native validity alone cannot hide it.

## Consequences

- Accessibility-declared required fields are visible in the operator checklist.
- Native browser validity is not overextended beyond constraints the browser actually enforces.
- Older observations remain compatible: an existing `required=true` becomes native-required unless newer provenance is present, preserving prior native behavior.
- This does not add custom-widget semantics, infer required state from prose, read current values, or claim provider-side acceptance.

## Alternatives rejected

- Ignoring ARIA requiredness leaves accessibility-driven portals incomplete.
- Mapping ARIA requiredness directly into native validity creates false completion signals.
- Parsing asterisks or words such as “required” from labels is too ambiguous for a deterministic safety boundary.
