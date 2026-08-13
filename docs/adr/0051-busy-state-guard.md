# ADR 0051: Busy state guard

## Status

Accepted for Busy State Guard `v0.42.0-alpha.1`.

## Context

A portal may mark an individual control or its containing form `aria-busy=true` while asynchronous validation, option loading, or a remote update is pending. Native HTML validity may already pass during that interval. Treating the control as satisfied or writable can race the provider and make review evidence stale.

## Decision

Observed controls add `control_busy`, `form_busy`, and combined `busy` booleans. Control provenance is true for case-insensitive `aria-busy=true` on the element. Form provenance is true for the same declaration on the nearest containing form. The combined signal is true when either applies.

Busy controls remain visible in bounded observation. The desktop excludes them from detected-field binding, required-field coverage classifies them as manual before native-valid completion, and approved execution independently rejects them before constructing a browser action.

## Consequences

- Provider-declared pending state conservatively withholds automation authority.
- Existing observations default the three fields to false and remain subject to current page, fingerprint, visibility, and actionability checks.
- Only booleans are recorded; current values, raw attribute text, status messages, full HTML, and timing guesses are excluded.
- The user recaptures the page after the provider clears the busy state.

## Alternatives rejected

- A fixed sleep cannot prove that provider-side work completed and adds race conditions.
- Trusting native validity while ARIA busy is true can report completion before remote validation settles.
- Capturing live-region or status text would retain unnecessary portal and candidate content.
