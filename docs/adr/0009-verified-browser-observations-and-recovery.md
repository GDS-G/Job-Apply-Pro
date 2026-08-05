# ADR 0009: Verified browser observations and recovery

- Status: Accepted
- Date: 2026-08-05
- Build: Browser Runtime `v0.4.0-alpha.1`

## Context

DOM mutations and successful Playwright calls do not prove that a portal accepted an action. Long application workflows must also recover after browser, backend, Windows, network, MFA, CAPTCHA, or takeover interruptions without guessing their prior state.

## Decision

Every browser action declares its tool, semantic target, preconditions, intended result, timeout, verification rule, retry policy, permission, and confirmation state. Role, label, text, and test-id locators are preferred; CSS, XPath, accessibility selectors, and coordinates remain explicit fallbacks. An action is recorded as verified only after its postcondition succeeds.

After session creation and verified actions, the service persists a workflow checkpoint containing the session identifier, origin, page classification, URL, protected browser-storage reference, screenshot reference, page fingerprint, trace reference, pending-action state, and retry count. The protected payload uses the existing context-bound AES-256-GCM envelope.

Observations are bounded and purpose-specific: URL/title, portal and page classification, tabs, accessibility summary, relevant controls, visible text, validation messages, modals, console/network failures, upload/download status, screenshot, prior action, and a deterministic structural fingerprint. Full HTML and session tokens are excluded.

## Consequences

- Workers can restart at the current URL with persistent storage and compare fresh evidence.
- Screenshots and traces support diagnosis without making them authoritative workflow state.
- Failed verification is persisted as an action result and never silently treated as success.
- Observation size is bounded, but portal-specific adapters may later need additional redacted fields.
