# ADR-0074: Guided application workspace

## Status and scope

Accepted as the source design for Guided Application Workspace
`v0.64.0-alpha.1`.

This milestone makes the desktop's development surfaces operate as one selected
application workspace. It does not add a workflow transition, infer permission,
enable production submission, reconcile an uncertain external effect, or claim
that a named portal/provider is production-ready.

## Decision

The durable workflow queue is the renderer's single application-selection
authority. Selecting a workflow binds the active profile, candidate knowledge,
application answers, reviewed field bindings, field executions, document
previews, Reference ATS run, supervised portal run, challenge session,
correlated communications and selected-browser effect warning to that exact
workflow/application/profile identity.

Selection changes clear application-specific previews and lists before loading
the next application. Candidate knowledge may be retained only when the profile
identity is unchanged. Knowledge, answers, bindings and executions load together;
the previous load is cancelled logically so a late response cannot overwrite a
newer selection. Queue selection is disabled while an existing reviewed mutation
is in flight. Every visible application selector changes the central workflow
selection and is controlled by the selected application identifier.

Reference and supervised portal panels may display only runs whose
`workflow_id` equals the selected workflow. There is no fallback to the newest
run belonging to another application. Challenges and communication counts use
the same exact workflow correlation. A workspace warning is shown only when an
unresolved `BROWSER_ACTION` subject belongs to a browser session for the selected
workflow.

## Guided navigation boundary

`ApplicationWorkspaceGuide` presents five linked areas:

1. job discovery/readiness;
2. candidate documents/evidence;
3. application answers, fields and portal execution;
4. challenges and user intervention; and
5. communication/scheduling follow-up.

The suggested destination is presentation-only. It is derived from the saved
workflow state and already loaded scoped counts/statuses. It cannot advance a
workflow or enable a control. Backend `allowed_controls`, exact review
fingerprints, provider configuration, effect-ledger admission and all existing
service policies remain authoritative.

An unresolved selected-browser effect suggests Operations and explains that the
operator must inspect/reconcile evidence. The guide exposes no retry, clear or
resolve mutation. `FAILED_TERMINAL` likewise points to Operations; submission and
tracking states point to follow-up without claiming provider delivery.

## Renderer responsibilities

The renderer owns only selection, stale-view clearing, cancellable loading,
status presentation and in-page navigation. Business logic remains in the
Python services and repositories. The Electron preload surface is unchanged;
context isolation stays enabled and Node.js APIs are not exposed to React.

Stable section identifiers support guide and notification navigation:
`job-discovery`, `job-readiness`, `candidate-evidence`, `application-portal`,
`challenge-framework`, `communication-scheduling` and `operations-recovery`.

## Validation and remaining gates

Regression coverage proves that an unselected portal run is hidden, selecting a
different workflow reloads that profile/application's details, every application
selector follows the queue selection, and the existing reference-fixture review
control remains independently governed. The normal desktop accessibility,
format, lint, type and production-build gates remain required.

The cohesive workspace removes cross-application presentation/action hazards;
it does not complete named portal vertical slices, provider-specific remote
reconciliation, automatic forward-restore choice/resume, signed update/rollback
acceptance, authorized live-provider tests or physical Windows release-lab
validation.
