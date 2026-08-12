# ADR 0045: Positive visibility evidence for observed controls

## Status

Accepted for Visible-Control Form Readiness `v0.36.0-alpha.1`.

## Context

The browser selector excluded hidden and password input types but could still return controls hidden by CSS or layout. Those controls could consume the bounded observation limit, influence the structural page fingerprint, appear in binding selection, and be classified as current required work even though the operator could not see or review them. A semantic locator alone does not prove current visibility.

## Decision

The isolated Playwright worker computes visibility without reading control values. A control is observable only when computed `display` is not `none`, computed `visibility` is not `hidden`, and its current bounding rectangle has positive width and height. Filtering happens before the 100-control bound and native radio-group aggregation. Every emitted control carries `visible=true` as positive evidence.

`BrowserObservedControl.visible` defaults to false when older serialized observations are read. Required-field coverage considers only required controls with positive visibility evidence. The desktop binding selector lists only positively visible controls, and approved-field execution rejects a control without current positive visibility evidence even if a stale record contains a locator.

## Consequences

- CSS-hidden, zero-layout, and conditionally absent controls cannot appear ready, consume observation capacity, or receive an approved browser action.
- Controls that become visible later require a fresh capture and receive their then-current page fingerprint and visibility evidence.
- Existing observations remain readable but must be recaptured before coverage or approved execution can trust them.
- Visibility is a point-in-time layout signal, not proof that a control is unobscured, usable, semantically correct, or accepted by the provider. Playwright actionability and exact postcondition checks remain required.
- Password values, current field values, validation messages, full HTML, and session material remain excluded.

## Alternatives rejected

- Trusting locator visibility only at action time leaves hidden controls in coverage, binding, and fingerprint inputs.
- Persisting hidden controls with `visible=false` still lets them consume the bounded capture and increases accidental downstream use.
- Treating absent visibility metadata as true would allow old observations to bypass the new safety invariant.
