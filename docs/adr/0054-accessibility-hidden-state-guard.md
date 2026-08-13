# ADR 0054: Accessibility hidden-state guard

## Status

Accepted for Accessibility Hidden-State Guard `v0.45.0-alpha.1`.

## Context

A control can have positive CSS layout visibility while the control itself or an ancestor declares `aria-hidden=true`. Such a control is removed from the accessibility tree and may be a stale, decorative, duplicated, or transition-only portal surface. CSS visibility alone therefore does not establish that it is an appropriate automation target.

## Decision

The browser worker records `accessibility_hidden` plus `direct_accessibility_hidden` and `inherited_accessibility_hidden`. Case-insensitive `aria-hidden=true` on the control or its nearest matching ancestor contributes to the combined state; explicit false does not.

Accessibility-hidden controls remain in bounded observation for operator context. The desktop excludes them from detected binding, coverage keeps them manual before native-valid completion, and approved execution independently rejects them before sending an action.

## Consequences

- CSS-visible controls removed from the accessibility tree cannot enter the approved execution path.
- Existing observations remain compatible because all three fields default false.
- Only boolean provenance is recorded; raw ARIA text, ancestor identity, values, and HTML remain excluded.
- A portal must be recaptured after accessibility-hidden state changes.

## Alternatives rejected

- Folding accessibility-hidden into CSS visibility would erase useful provenance and hide manual-review context.
- Ignoring ancestor state would miss the common container-level declaration.
- Treating any nonempty aria-hidden value as true would misclassify explicit false.
