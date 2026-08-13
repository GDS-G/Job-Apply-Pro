# ADR 0050: Readonly control guard

## Status

Accepted for Readonly Control Guard `v0.41.0-alpha.1`.

## Context

A portal may expose a provider-managed or computed field using native `readonly` or accessibility metadata using `aria-readonly=true`. Such a control can remain visible and locatable while refusing or semantically prohibiting edits. Treating it as ordinarily actionable would offer a misleading binding and fail late during execution.

## Decision

Observed controls add `native_read_only`, `accessible_read_only`, and combined `read_only` booleans. Native provenance is true when the element has `readonly`; accessible provenance is true only for case-insensitive `aria-readonly=true`. The combined signal is true when either declaration applies.

Readonly controls remain in the positive-visibility observation for user review. The desktop excludes them from detected-field binding, required-field coverage classifies them as manual, and approved field execution independently rejects them before constructing a browser action.

## Consequences

- Provider-managed values remain visible to the operator without being granted automation authority.
- Existing observations default all readonly fields to false and must still satisfy current page, fingerprint, visibility, and actionability checks.
- The app records only booleans; it does not capture current values or infer readonly state from CSS, prose, or provider-specific classes.
- ARIA readonly state is author metadata and may be stale, but it conservatively wins over DOM writability.

## Alternatives rejected

- Waiting for Playwright fill to fail would perform an avoidable attempted write and produce a late, provider-dependent error.
- Excluding readonly controls from all observation would hide useful provider-managed required-field context from the user.
- Inferring readonly state from CSS classes, opacity, or nearby text is not deterministic enough for authorization policy.
