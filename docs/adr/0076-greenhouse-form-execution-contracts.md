# ADR-0076: Greenhouse form execution contracts

- Status: Accepted
- Date: 2026-09-14
- Build: Greenhouse Form Execution Contracts `v0.66.0-alpha.1`

## Context

The reviewed Greenhouse launch in v0.65 binds a ready saved job, immutable resume, exact origin, and native user confirmation to the first durable supervised-run evidence. Once the visible browser reaches an application form, however, the generic page classification alone cannot prove that required controls are complete, that an upload is new and targets the selected file, that a custom widget is safe, or that a click reached the expected later stage. Generic field execution and five replay page labels are not a Greenhouse compatibility claim.

## Decision

Job Apply Pro computes a Greenhouse-only `GreenhouseFormContractAssessment` from the current privacy-bounded browser observation. The assessment accepts only HTTPS `greenhouse.io` origins and the recognized application, document, questionnaire, review, and confirmation stages. It binds the current page fingerprint, required-control classifications, the unique navigation control, validation-error count, action class, and expected postcondition under `greenhouse-form-execution-contract/1`.

Required native controls are either already constraint-valid, eligible for the existing one-field reviewed execution path, pending exact document upload review, or blocked for visible user intervention. Disabled, readonly, busy, inert, accessibility-hidden, repeated, unlocatable, signature, disclosure, legal-attestation, and custom controls never inherit generic authority. Optional custom controls remain visible but do not make a required-field completeness claim. Ambiguous or missing navigation prevents `ready_to_advance`.

Document-upload verification requires all of the following: the reviewed control is still exactly one file input with the same semantic locator; the browser result is one confirmed `UPLOAD` action; the action path basename equals the reviewed supported `.pdf`, `.doc`, or `.docx` filename; that filename was absent before the action and appears exactly once afterward; the observation remains on the exact Greenhouse origin and form stage; and upload proof comes from the post-action observation rather than a fabricated value rule. A filename observation does not prove file bytes, so selected immutable-version SHA-256 retention remains a separate requirement.

Navigation verification requires the current assessment fingerprint, complete required controls, one reviewed click targeting the unique navigation locator, a verified browser result, the exact same origin, a changed page fingerprint, and a recognized later Greenhouse stage. Final submission remains outside this contract and retains the separate default-off policy, current review fingerprint, cancel-default native confirmation, one submit control, and identifier-backed confirmation.

The runtime assessment is returned only as transient supervised-run metadata; no candidate values, file paths, or new database rows are persisted. A versioned sanitized corpus executes success and refusal cases for all five stages, native required fields, document upload, searchable custom widgets, optional versus blocking controls, navigation, final submission, stale reviews, same-page transitions, origin escape, unsafe filenames, mismatched action files, and pre-existing upload names.

## Consequences

- The desktop can show why a Greenhouse page is or is not ready for a separately reviewed next step.
- Form-contract fingerprints are current-page review evidence, not action authority by themselves.
- Generic field bindings retain their existing answer, revision, page, locator, native-confirmation, and durable-effect gates.
- Sanitized fixtures establish deterministic source behavior only; `live_validated_page_types` remains empty and `production_enabled` remains false.
- Actual reviewed upload dispatch, reviewed navigation dispatch, authorized live acceptance, and confirmed exact-document retention remain later work.

## Alternatives rejected

- Treating any Greenhouse-branded page with a submit label as a complete multi-page adapter would produce false readiness claims.
- Trusting `upload_status` without comparing the admitted action and before-state could reuse stale evidence or misidentify the file.
- Automatically clicking a visible `Next` control would bypass required-field completeness, origin, stage, and postcondition checks.
- Treating ARIA comboboxes as native selects would apply unsupported generic semantics to provider custom widgets.
