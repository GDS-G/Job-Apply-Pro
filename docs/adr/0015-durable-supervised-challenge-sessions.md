# ADR 0015: Durable supervised challenge sessions

- Status: Accepted
- Date: 2026-08-05
- Build: Challenge Framework `v0.8.0-alpha.1`

## Context

Portal workflows encounter CAPTCHAs, screening questionnaires, quizzes, and timed assessments whose state can be lost across interruptions. Treating these pages as ordinary forms would allow stale answers, hidden timer expiry, model overreach, or false completion. Challenge support needs a durable contract without granting production-site or provider authority.

## Decision

The backend owns a persisted challenge session tied to one workflow and browser session. Detection records kind, provider signatures, page fingerprint, resume state, questions, timer, and append-only events. Browser controls are mapped to typed questions, and each answer must pass semantic post-action verification before it is stored as verified. Recovery re-observes the page; a changed fingerprint preserves answer values but invalidates verification and clears review readiness.

CAPTCHAs always transition to `CAPTCHA_REQUIRED` and require direct user intervention. The framework accepts completion only when a fresh observation no longer detects the CAPTCHA, then restores the saved workflow state. Legal attestations and signatures follow the same intervention boundary.

Deterministic suggestions may use encrypted contact fields or approved, locked answer-library entries permitted for applications. AI use is expressed only as capability and tier recommendations consumed by the governed gateway: fast text, strong reasoning, multimodal, or long context, with low-confidence escalation. Model output cannot verify an answer or authorize completion.

Assessment completion requires all required answers to be verified, an unchanged review fingerprint, and explicit `COMPLETE CHALLENGE` confirmation. The workflow advances only after an approved completion-page signal.

## Consequences

- Timers, answers, interruptions, and recovery decisions survive backend restarts in SQLite.
- CAPTCHA services, solver credentials, and model-based bypasses remain outside the architecture.
- Answer provenance and verification are inspectable through authenticated APIs and desktop UI.
- Production portal support still requires separate adapter and rollout decisions.
