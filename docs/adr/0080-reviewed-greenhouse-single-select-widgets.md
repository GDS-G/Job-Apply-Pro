# ADR-0080: Reviewed Greenhouse single-select widgets

- Status: Accepted
- Date: 2026-09-15
- Build: Reviewed Greenhouse Single-Select Widgets `v0.70.0-alpha.1`

## Context

The Greenhouse form contract previously classified every custom widget as visible user intervention. Some accessible single-select controls expose a narrower deterministic shape: one visible input with role `combobox`, an expanded `listbox` popup, one controlled visible listbox, and unique visible enabled option labels. Treating every such field as manual leaves an avoidable gap, but treating generic custom widgets like native selects would permit ambiguous global option clicks, hidden listboxes, multiselect behavior, legal controls, or stale widget state.

## Decision

Job Apply Pro recognizes only an expanded, searchable, visible and enabled input combobox that controls exactly one visible non-multiselect listbox. The observation must contain at least one non-empty trimmed option label, labels must be case-insensitively unique, the control must have one exact semantic locator, and it cannot be repeated, readonly, busy, inert, accessibility-hidden, disabled, or a legal attestation. The Greenhouse form assessment classifies only that shape as `REVIEW_FIELD`; all other custom widgets remain `USER_INTERVENTION`.

The reviewed field is represented by the dedicated binding kind `SINGLE_SELECT_WIDGET`. Only reviewed `YES_NO` and `MULTIPLE_CHOICE` answers may bind to it. The renderer derives this kind only from a current Greenhouse `REVIEW_FIELD` contract; it does not expose the kind in manual metadata choices. Selecting a detected control disables unrelated manual metadata inputs so browser validation cannot block the trusted binding preview.

Execution retains the v0.68 run, page, binding, answer-revision and Greenhouse form-review gates. The backend freshly observes and reassesses the page, requires one current matching contract, maps the trusted custom control to `SINGLE_SELECT_WIDGET`, decrypts one reviewed answer, and requires one exact visible option-label match. It dispatches `CHOOSE_CONTROLLED_OPTION` with `VALUE_EQUALS` verification and sensitive-value redaction through the durable browser external-effect ledger.

The browser worker scopes lookup to the combobox's single current `aria-controls` identifier and that exact controlled `role=listbox`; it never searches all page options. Immediately before the click it rechecks the target is still a visible enabled input combobox with `aria-haspopup=listbox` and `aria-expanded=true`, the owned listbox is visible and not multiselect, and exactly one enabled visible option has the reviewed accessible name. If the widget collapsed or changed after observation, the worker refuses rather than opening it. A dispatched failure or ambiguous result is consumed and returns to takeover without automatic retry.

## Consequences

- One bounded Greenhouse single-select widget can use the existing reviewed-answer and one-field execution flow without granting generic custom-widget authority.
- Custom widgets on other portals, collapsed widgets, multiple controlled elements, hidden listboxes, duplicate labels, multiselects, legal/signature controls, repeated controls, and unlocatable controls remain manual.
- Internal option values are not execution authority; selection uses the exact reviewed visible label within the one controlled listbox.
- Sanitized contract tests, binding/coverage tests, renderer tests and a real local Chromium worker fixture validate the boundary, but do not establish live Greenhouse compatibility.
- Greenhouse production enablement remains false and live-validated page types remain empty pending authorized acceptance.

## Alternatives rejected

- A page-wide role/name option click could select an unrelated listbox and is not deterministic.
- Reopening a collapsed widget at dispatch would act on state different from the reviewed observation.
- Using internal option values would make provider implementation details renderer-controlled authority.
- Allowing manual construction of `SINGLE_SELECT_WIDGET` in the renderer would bypass provider assessment.
- Extending this contract to multiselect, contenteditable, repeated, legal, signature, hidden, ambiguous, or other-portal widgets without a separate reviewed policy would overstate the proven boundary.
