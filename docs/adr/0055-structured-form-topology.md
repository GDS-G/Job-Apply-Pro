# ADR 0055: Structured form topology

## Status

Accepted for Structured Form Topology `v0.46.0-alpha.1`.

## Context

Job portals commonly repeat the same named field in work-history or education sections, reveal conditional questions, and render searchable choice controls as ARIA combobox/listbox widgets. A flat label and control kind cannot distinguish repeated instances or explain why a custom widget is not executable. Blindly reusing a label locator can target more than one element.

## Decision

The browser worker records a bounded semantic section path, repeat-group name, repeat index/count, conditional-region name and visible trigger text, plus searchable/listbox popup state and visible option labels. Repeat discovery uses explicit `data-repeat-group` metadata when available and otherwise detects duplicate same-name, same-tag, same-type controls; radio and checkbox groups are excluded from duplicate-field inference.

ARIA combobox and listbox implementations that are not native selects are classified as `CUSTOM`. Repeated controls and custom widgets remain visible in review, but the generic execution path does not act on them. Repeated controls require a provider-specific unique locator; custom widgets continue to require visible user handling until a reviewed adapter defines its transitions and exact postcondition.

## Consequences

- Operators can distinguish repeated and conditional questions without exposing current values or raw markup.
- Searchable widget options can inform reviewed answer compatibility while automation remains disabled.
- Existing serialized observations remain compatible through conservative defaults.
- Provider-specific adapters must prove uniqueness and verification rather than assuming label uniqueness.
- Topology metadata is capped and sanitized with the same observation limits as other browser metadata.

## Alternatives rejected

- Executing the first matching repeated label could populate the wrong employment or education record.
- Treating ARIA comboboxes as native selects would send unsupported actions and provide invalid verification.
- Capturing raw HTML or DOM ancestry would exceed the privacy-bounded observation contract.
