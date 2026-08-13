# ADR 0052: Inherited native disabled state

## Status

Accepted for Inherited Disabled State Guard `v0.43.0-alpha.1`.

## Context

HTML permits a disabled fieldset to disable descendant controls even when those controls do not carry their own `disabled` attribute. The first legend child is a defined exception. Attribute-only observation therefore misclassified some genuinely disabled controls as actionable.

## Decision

The worker uses the browser's `:disabled` matching semantics for native disabledness. It emits `inherited_disabled=true` when a control matches `:disabled` without its own disabled attribute. Combined `disabled` and `native_disabled` remain true for both direct and inherited native state.

The existing desktop binding exclusion, manual required-field classification, and approved-execution refusal consume the normalized combined signal. The browser, rather than custom ancestor traversal, determines the fieldset and first-legend rules.

## Consequences

- Native disabledness agrees with browser HTML semantics, including nested fieldsets and the first-legend exception.
- Existing observations remain readable; inherited provenance defaults false.
- Only booleans are recorded. No values, HTML, ancestor identifiers, or provider content are added.
- ARIA disabled provenance remains separate and continues to contribute to the combined signal.

## Alternatives rejected

- Checking only `hasAttribute('disabled')` misses inherited native disabledness.
- Manually walking fieldsets risks reimplementing evolving browser edge cases incorrectly.
- Dropping inherited-disabled controls from observation would hide useful manual-review context.
