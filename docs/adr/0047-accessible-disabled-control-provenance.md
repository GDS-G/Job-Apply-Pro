# ADR 0047: Accessible disabled-control provenance

## Status

Accepted for Accessible Disabled Control Guard `v0.38.0-alpha.1`.

## Context

Portals and component libraries may declare controls unavailable through `aria-disabled=true` without the native HTML `disabled` attribute. Such an element can remain focusable or programmatically writable, so relying only on native disabledness could offer it for binding or execute an action the interface says is unavailable.

## Decision

Observed controls retain one combined `disabled` boolean and add `native_disabled` and `accessible_disabled` provenance. The worker recognizes `aria-disabled=true` case-insensitively and does not infer disabled state from classes, opacity, label text, or pointer styling.

The combined disabled signal is true when either provenance signal is true. The desktop excludes combined-disabled controls from detected binding choices. Required-field coverage classifies them as manual. Approved-field execution rejects them before action construction. Existing observations with `disabled=true` and no provenance normalize as native-disabled for backward compatibility.

## Consequences

- Accessibility-disabled controls cannot be automated merely because the DOM permits a write.
- The separate provenance supports diagnostics without weakening the combined fail-closed policy.
- Visibility and disabledness remain independent: a visible disabled control may be observed for diagnostics but cannot enter the approved action path.
- This does not infer portal business state, read current values, or prove that enabled controls are actionable.

## Alternatives rejected

- Trusting only native `disabled` ignores common accessible component state.
- Treating `aria-disabled` as diagnostic-only permits automation against an explicitly unavailable control.
- Inferring disabledness from CSS or prose is too ambiguous for a deterministic enforcement boundary.
