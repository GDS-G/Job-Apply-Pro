# ADR-0025: Bound external document conversion and OCR

- Status: Accepted
- Date: 2026-08-11
- Build: Document Ingestion Resilience `v0.16.0-alpha.1`

## Context

Candidate material can arrive as legacy binary DOC or as image-only PDF. Python's DOCX and PDF text parsers cannot safely or accurately cover those inputs alone. A converter or OCR engine increases import coverage, but accepting arbitrary commands, silently trusting converted output, or rendering attacker-controlled pages without resource limits would expand the local attack surface. PyMuPDF was considered for OCR integration but its AGPL/commercial licensing was not introduced into this repository without an explicit compatible licensing decision.

## Decision

Legacy DOC conversion is opt-in and accepts only an exact absolute path whose resolved filename is LibreOffice `soffice`, `soffice.exe`, or `soffice.com`. The process receives fixed arguments, no stdin, no shell, a minimal allowlisted environment that excludes backend secrets, an isolated temporary user profile/home/temp/app-data workspace, a bounded timeout, and a bounded output file. The resulting DOCX is treated as untrusted input, checked for archive entry and expanded-size limits, and parsed again. The encrypted original remains the retained candidate version; parser provenance records the conversion boundary.

Scanned-PDF OCR is also opt-in and accepts only an exact absolute `tesseract` executable. Ordinary PDF text extraction runs first. Only pages without meaningful text are rendered with pypdfium2, whose Python bindings are BSD-3-Clause/Apache-2.0 and whose PDFium binary license material is included in the packaged backend. OCR is bounded by total PDF pages, OCR pages, DPI, rendered pixels, per-page output bytes, helper timeout, block count, and character count. Helper stdout/stderr is discarded; text is read only from the expected bounded output file. Recovered blocks retain page number, OCR kind, language, and DPI. Skipped or incomplete work produces user-visible warnings; OCR output remains proposed evidence requiring human review.

## Consequences

LibreOffice, Tesseract, and Tesseract language data are owner-installed external prerequisites and are disabled by default. Their mere configuration is not a claim that every DOC or scan will preserve layout or read correctly. The application gains deterministic failure messages and test seams without acquiring arbitrary command execution or silently elevating OCR text to verified evidence. Future layout engines must preserve the same provenance, resource, licensing, and explicit-configuration boundaries.
