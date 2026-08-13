# ADR 0049: Accessible invalid-state guard

## Status

Accepted for Accessible Invalid State Guard `v0.40.0-alpha.1`.

## Context

A portal may apply business or remote validation and expose the result through `aria-invalid` while the native HTML constraints still report `validity.valid=true`. Treating native validity as sufficient in that state can hide a required field from the unresolved checklist.

## Decision

Observed controls add one privacy-bounded `accessible_invalid` boolean. The worker treats an absent or case-insensitive `false` attribute as false; every other non-empty `aria-invalid` token is true, including specification tokens such as `grammar` and `spelling`. It does not return the attribute token, current value, or validation message.

Required-field coverage may classify a control `SATISFIED_ON_PAGE` only when it is native-required, participates in native validation, is natively constraint-valid, and is not accessibility-invalid. An invalid control continues through its existing manual, unbound, stale, ambiguous, ready, or verified classification.

## Consequences

- Provider-declared accessible invalidity wins over a weaker native-valid signal.
- The boolean is useful without retaining validation content that may expose candidate data.
- The signal is point-in-time author state, not proof that a field is correct when false or that provider-side validation has completed.
- Existing observations default to false for compatibility and must still satisfy current fingerprint and visibility rules.

## Alternatives rejected

- Trusting native validity alone ignores remote and business validation surfaced accessibly.
- Returning the raw `aria-invalid` token or validation message adds unnecessary data without changing the binary coverage decision.
- Treating only literal `true` as invalid would ignore the standard `grammar` and `spelling` values.
