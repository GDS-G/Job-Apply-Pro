# ADR 0007: Durable supervised Workbench controls

- Status: Accepted
- Date: 2026-08-05
- Build: Workbench `v0.3.0-alpha.1`

## Context

Phase 3 requires the UI to start and control a mock workflow, display live events, recover after a worker restart, and surface errors without implying that real applications are being submitted.

## Decision

Workbench mock workflows reuse the production state-machine vocabulary and persisted Core application/event tables. Advance, pause, resume, retry, takeover, stop, and close actions resolve to validated deterministic transitions. `WorkbenchRepository.apply_transition()` verifies the expected current state and commits the workflow event plus application state in one SQLAlchemy transaction.

The renderer polls typed snapshots every two seconds and also receives backend lifecycle status events. A snapshot joins non-sensitive candidate display data, job identity, application state, progress, and the ordered event history. No automatic timer advances a workflow; every mock transition is user initiated.

## Consequences

- Restart recovery is ordinary database readback rather than reconstructed UI state.
- State/event divergence is prevented for Workbench controls.
- The same UI control contract can later target real supervised workers.
- Progress percentages are presentation metadata and do not prove portal completion or submission.
