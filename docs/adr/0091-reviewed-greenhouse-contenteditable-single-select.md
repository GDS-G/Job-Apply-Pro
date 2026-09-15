# ADR-0091: Reviewed Greenhouse contenteditable single-select

- Status: Accepted
- Build: Reviewed Greenhouse Contenteditable Single-Select `v0.81.0-alpha.1`

## Context

ADR-0080 admitted one narrow Greenhouse single-select shape: an expanded input combobox that owns exactly one visible listbox. Some accessible provider widgets expose the same semantics through a contenteditable `div` or `span`. Treating every contenteditable element as an input would grant broad editing authority, while leaving this exact shape manual prevents the existing deterministic option contract from covering an equivalent accessible control.

## Decision

The browser worker records `widgetContenteditable` from the live DOM using `element.isContentEditable`; the backend normalizes it to `BrowserObservedControl.widget_contenteditable`. A custom control is eligible only when it is an `input`, or a `div`/`span` whose live `isContentEditable` value is true, and every existing ADR-0080 invariant also holds: exact combobox role, `aria-haspopup=listbox`, expanded state, one controlled visible listbox, no multiselect semantics, visible/enabled/non-readonly/non-busy/non-inert/accessibility-visible state, no repeated/conditional/legal/signature semantics, a semantic locator, and unique nonempty enabled option labels.

The policy identifier advances to `greenhouse-form-execution-contract/2`; v0.81 reviews therefore cannot be mistaken for reviews produced by the narrower historical contract.

ARIA-labelledby custom comboboxes use one exact role-and-accessible-name locator. Dispatch rechecks the live tag, editability, role, popup, expansion, controlled-listbox ownership, visibility, enabled state, multiselect state, and unique exact option label before one scoped option click. `VALUE_EQUALS` reads `value` only from a native input, textarea or select and reads normalized visible text only from a live contenteditable `div`/`span`; a page-added `value` property on a contenteditable element cannot satisfy verification. A changed or noneditable control fails before option activation; an uncertain response is never retried.

## Consequences

The existing reviewed Greenhouse field execution and approval contract can execute one additional deterministic widget representation without adding generic typing, DOM mutation, or widget-opening authority. Contenteditable elements outside `div`/`span`, collapsed widgets, multiple or hidden controlled listboxes, disabled options, repeated controls, ambiguous labels, multiselects, legal attestations, signatures, and unrecognized custom widgets remain manual. No schema migration is required. Controlled fixtures do not establish compatibility with live Greenhouse or any other provider.
