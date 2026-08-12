# ADR-0032: Conservative layout-aware document ingestion

- Status: Accepted
- Build: Layout-Aware Resume Ingestion `v0.23.0-alpha.1`

## Context

The candidate-knowledge boundary already supports bounded PDF/DOCX parsing, opt-in OCR, legacy conversion, encryption, hashes, provenance, and explicit claim review. Ordinary PDF extraction nevertheless stored one page-sized block in content-stream order, and DOCX extraction appended every table after every paragraph. Both behaviors can distort common résumé reading order before claim proposal and retrieval.

PDF files do not provide a reliable semantic reading-order layer. A layout improvement must therefore be explainable, bounded, deterministic, and reviewable rather than presented as universally correct visual understanding.

## Decision

New PDF imports reject a decoded page content stream above 20 MiB, then use pypdf fixed-width layout mode without inferred vertical blank lines. Each non-empty rendered line is split only on runs of four or more spaces. Column-major ordering activates only when at least two rows contain multiple segments and at least two repeated clustered starts are separated by twelve character cells. Content before the first multi-column row remains first; later content is ordered left column top-to-bottom, then subsequent columns. The import records page, source row, inferred column, block style, parser version, and a user-visible review warning whenever the heuristic activates.

New DOCX imports use `Document.iter_inner_content()` so top-level paragraphs and tables remain in document order. Table rows record table and row coordinates. Optional `row`, `column`, and `table` fields extend `LayoutBlock`; missing fields retain defaults, so existing encrypted extraction records remain valid and require no migration.

OCR, legacy conversion, file/archive/page/character/block limits, encryption, content hashes, evidence identity, claim review, and downstream approval rules do not change.

## Consequences

- Common two-column text résumés and mixed paragraph/table DOCX documents have more useful deterministic reading order.
- Parser provenance advances to `pypdf-layout/2` and `python-docx-layout/2`; converted DOC files include the latter suffix.
- Column ordering is deliberately conservative and may leave ambiguous pages in line order.
- Graphics, floating text boxes, spanning rows, nested tables, and unusual PDF geometry still require owner review or a future governed visual parser.
- Tests use generated sanitized documents; no candidate résumé, account credential, or private provider data enters source or CI.
