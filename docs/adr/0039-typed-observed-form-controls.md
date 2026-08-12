# ADR 0039: Typed observed form controls

- Status: Accepted
- Date: 2026-08-12
- Build: Observed Form Control Capture `v0.30.0-alpha.1`

## Context

Browser observations previously exposed controls as unvalidated dictionaries. The binding UI therefore required operators to retype labels, kinds, options, constraints, stable keys, and page fingerprints. That weakens the chain between the visible supervised page and an approved application-answer binding.

## Decision

Normalize every privacy-safe browser control into a frozen `BrowserObservedControl` contract. The worker never includes password controls or current field values. The contract records a deterministic control key, semantic kind, visible label/group/text, non-secret identity metadata, required/disabled/checked state, select or radio options, visible length/number/date constraints, legal-attestation detection, and an optional semantic locator.

Supervised portal snapshots expose controls only when the persisted run fingerprint still matches the browser session's latest observation. The desktop binding form can select that exact control and derive the portal, page fingerprint, control key, kind, label, options, and constraints without manual transcription. Manual sanitized entry remains available for unsupported widgets.

This release captures and transports metadata only. It does not execute a binding, fill a field, store a field value, or authorize submission.

## Consequences

Field-binding approval is now grounded in the current supervised observation and can later support exact re-observation before execution. Unsupported and ambiguous controls remain review work. DOM restructuring can change deterministic keys and therefore requires a new review instead of silently reusing a stale binding.
