# ADR 0048: Exact accessible-name control locators

## Status

Accepted for Accessible Control Labels `v0.39.0-alpha.1`.

## Context

Some portals label native controls with `aria-labelledby` instead of an HTML label or `aria-label`. The browser observation previously omitted that accessible name, leaving a user-visible control unlabeled or non-locatable. Reusing a LABEL locator is incorrect because Playwright's label lookup does not reliably address `aria-labelledby` controls.

## Decision

The worker resolves the space-separated IDs in `aria-labelledby`, concatenates the referenced text in declared order, collapses whitespace, and bounds the result to 300 characters. Missing references contribute no text. The worker records one bounded `label_source`: `ARIA_LABELLEDBY`, `ARIA_LABEL`, `HTML_LABEL`, `WRAPPING_LABEL`, or `NONE`.

An `ARIA_LABELLEDBY` native control receives an exact ROLE locator whose role is derived from its normalized native control kind and whose name is the resolved accessible name. Other labelled controls retain exact LABEL locators. ARIA-labelled radio options receive exact `ROLE radio` locators. Required-field coverage and approved radio execution accept only exact native-label or exact accessible-role radio option locators.

## Consequences

- Controls with deterministic accessible names can enter reviewed binding and verified execution without fabricating an HTML label relationship.
- Multi-node accessible names are normalized predictably, and missing referenced IDs fail softly without exposing DOM markup.
- Locator provenance remains explicit and testable.
- The implementation does not resolve shadow DOM or cross-origin references, inspect CSS-generated content, or persist full HTML.

## Alternatives rejected

- Emitting a LABEL locator for `aria-labelledby` produced observation/execution disagreement.
- Using CSS selectors based on IDs would couple approved actions to opaque implementation identifiers instead of the user-visible accessible name.
- Parsing the full accessibility tree for every control would increase complexity and data exposure beyond the bounded need.
