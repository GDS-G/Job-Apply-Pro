# ADR 0057: Complex DOCX layout evidence

## Status

Accepted for Complex DOCX Layout Evidence `v0.48.0-alpha.1`.

## Context

Resume content can appear in nested tables or floating text boxes rather than ordinary document paragraphs. Ignoring that content loses candidate evidence, while claiming exact visual order from OOXML would be misleading. Drawings can also contain graphics with no machine-readable text.

## Decision

DOCX parser provenance advances to `python-docx-layout/3`. Nested tables are recursively flattened after their containing row with distinct table indexes, while direct cell paragraphs are kept separate so nested text is not duplicated. Text inside OOXML text-box content is captured as `DRAWING_TEXT` with `ooxml:textbox:visual-position-unverified` provenance.

The extraction emits one bounded warning when floating text is recovered without reliable visual placement and one when drawing content has no recoverable text. Existing archive, entry, block, character, conversion, encryption, claim-review, and evidence boundaries remain unchanged.

## Consequences

- Candidate text in common floating and nested DOCX structures becomes reviewable.
- The application never claims exact placement for floating content.
- Non-text graphics remain a human or future governed-vision review boundary.
- Legacy DOC conversion inherits the version-3 parser provenance.

## Alternatives rejected

- Silently dropping floating/nested content can omit material qualifications.
- Using aggregate `cell.text` duplicates nested-table text.
- Guessing graphic meaning or floating-object position would create unverified evidence.
