# ADR-0077: Reviewed Greenhouse form actions

- Status: Accepted
- Date: 2026-09-15
- Build: Reviewed Greenhouse Form Actions `v0.67.0-alpha.1`

## Context

The v0.66 Greenhouse contract can assess a current application page and verify the result of an upload or one-stage navigation, but it intentionally dispatches neither action. A safe executable slice must not let renderer-provided URLs, locators, paths, document identifiers, hashes, or confirmation phrases become authority. It must also preserve the existing durable browser-effect ledger and keep final submission, login, MFA, CAPTCHA, assessments, signatures, and legal attestations outside the new authority.

## Decision

Job Apply Pro adds a two-step backend preview and execution contract for exactly two Greenhouse form actions: `REVIEW_DOCUMENT_UPLOAD` and `REVIEW_NAVIGATION`. The request contains only the selected application, supervised run, action class, current control key, and form-review fingerprint. The backend recomputes the full reviewed-job readiness chain, verifies that the run belongs to the same workflow and current Greenhouse page, and derives every privileged value.

For an upload, the preview binds the exact immutable selected document version, filename, SHA-256, workflow, run, page fingerprint, form-review fingerprint, control, action, and policy version under `reviewed-greenhouse-form-action/1`. Immediately before execution the backend recomputes the preview, requires its exact fingerprint and a fixed main-process confirmation phrase, rereads the encrypted document, verifies its filename and SHA-256, and passes only the derived record to supervised execution. Decrypted staging validates the expected SHA-256 before writing a bounded plaintext file. The staged file is cleared in a `finally` path, including failed execution.

For navigation, the preview binds the exact current unique navigation control and requires every required control to be ready. Execution recomputes the same preview and performs one confirmed click on the still-observed semantic locator. Navigation can prove only a recognized later Greenhouse form stage; it explicitly cannot establish final application confirmation.

Electron main refetches the exact preview, compares every non-privileged request field, presents a cancel-default native warning, and injects the fixed confirmation phrase only after approval. Upload review shows the immutable filename/version/SHA without exposing the local path. The sandboxed renderer sends none of the URL, locator, path, version, hash, or phrase fields.

Both actions reuse `BrowserRuntimeService.execute_action`, so durable logical ownership and `DISPATCHING` evidence exist before browser I/O. The specialized post-action observation is the success proof; generic value verification is disabled for these actions. A changed page, review, origin, document, control, action, or failed specialized postcondition returns the browser to user takeover. An uncertain or failed action is consumed and is not retried automatically. The supervised evidence fingerprint includes the specialized postcondition kind and evidence fingerprint without expanding the persisted schema.

Final submission remains a separate default-off path requiring its own current review, native confirmation, unique submit control, and identifier-backed confirmation. No action in this release fills ordinary fields, handles custom widgets, logs in, bypasses security challenges, accepts legal terms, signs, or submits.

## Consequences

- The reviewed Greenhouse slice can upload the exact selected document and advance one ready form stage without trusting renderer privilege claims.
- SHA-256 verification closes the gap between immutable selection and plaintext upload staging; filename observation still does not prove what a remote portal retained.
- Failed or ambiguous postconditions produce durable evidence and user takeover, never automatic retry.
- Live compatibility is still unproven: portal entries remain `production_enabled=false`, live-validated page types remain empty, and supervised execution is disabled by default.
- Additional native-field composition, authorized live acceptance, other named portals, package qualification, signing, and physical installed-app validation remain future work.

## Alternatives rejected

- Letting the renderer submit the document path, URL, locator, hash, or confirmation phrase would move authority across the least-trusted boundary.
- Adding a Greenhouse-specific browser executor would bypass the durable external-effect ledger and duplicate safety policy.
- Treating a successful click or filename label as sufficient proof would ignore changed pages, stale uploads, and unknown remote state.
- Automatically retrying after a failed or uncertain result could duplicate an external effect.
- Reusing stage navigation for the final submit control would collapse a materially different legal and irreversible action into a lower-risk permission.
