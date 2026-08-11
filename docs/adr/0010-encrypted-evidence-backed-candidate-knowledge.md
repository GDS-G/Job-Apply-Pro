# ADR 0010: Encrypted evidence-backed candidate knowledge

- Status: Accepted
- Date: 2026-08-05
- Build: Candidate Knowledge `v0.5.0-alpha.1`

## Context

Resumes and supporting documents contain high-sensitivity personal data. Extractors can also misread layouts or infer incorrect facts. The application needs useful structured knowledge without treating imported text or generated output as authoritative.

## Decision

The backend accepts bounded PDF, DOCX, RTF, TXT, and Markdown files, extracts text and layout in memory, and stores both original bytes and extraction payloads as context-bound AES-256-GCM ciphertext. A content hash, parser metadata, document version, and evidence source preserve provenance. Binary `.doc` conversion remains outside the application trusted boundary.

Deterministic extractors may create proposed claims, but every proposal records its evidence location, confidence, verification status, permitted use, sensitivity, and current/superseded state. Only an explicit authenticated review may verify and lock a fact. A conflicting locked canonical fact fails closed instead of being silently replaced.

## Consequences

- Candidate plaintext is not stored in document files, extraction columns, or answer-library columns.
- Reviewers can trace a fact back to the exact imported version and extraction location.
- Extraction remains intentionally conservative and will miss facts that require future structured or AI-assisted interpretation.
- Multiple resume variants can coexist without creating multiple candidate identities.
