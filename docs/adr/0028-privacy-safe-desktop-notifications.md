# ADR-0028: Privacy-safe actionable desktop notifications

- Status: Accepted
- Date: 2026-08-11
- Build: Actionable Desktop Notifications `v0.19.0-alpha.1`

## Context

The product requirements call for in-app and native desktop alerts when a workflow needs direct user action, a provider message changes an application, a follow-up is due, or an operational task fails. Source records can contain employer names, job titles, senders, subjects, message bodies, challenge text, and diagnostics. Windows notifications can appear on a locked screen or be retained by the operating system, so copying source text into a notification would expand the privacy boundary.

## Decision

Electron main owns notification polling, deduplication, persistence, and native presentation. Every 60 seconds it reads existing authenticated local API contracts for workflows, challenge sessions, communication records, follow-ups, and backups, and combines them with desktop update state. Collection is bounded to 50 active items. At most five new native notifications are displayed per refresh, and at most 500 delivered identifiers are retained.

The renderer receives only a typed notification projection: deterministic identifier, category, generic title and body, destination, severity, and timestamp. Notification text never contains employer names, job titles, candidate names, message senders, recipients, subjects, bodies, follow-up reasons, provider identifiers, diagnostics, credentials, or tokens. Native delivery is disabled by default and must be enabled by the user. In-app alerts remain visible when native delivery is disabled or unsupported.

The local `notification-state.json` file stores only the native opt-in and bounded delivered identifiers. It has a 64 KiB read/write limit, rejects malformed state, and is written with owner-only permissions where supported. It is not a source of business truth. Workflow and communication records remain authoritative in the encrypted database.

Clicking a native or in-app notification focuses Job Apply Pro and navigates to one of four fixed destinations: workflows, challenges, communications, or operations. No arbitrary URL, HTML, source identifier, or renderer command crosses this boundary.

## Consequences

- Native notifications are actionable without exposing protected job-search content on the desktop.
- Stable source identifiers suppress repeat alerts across refreshes and restarts.
- Disabled or unsupported native delivery does not hide in-app action state.
- A poll or presentation failure is reported as a generic local-workspace error and does not interrupt workflow persistence.
- Windows toast appearance, Focus Assist behavior, locked-screen visibility, click activation, sleep/resume, and installer identity still require physical release-lab validation.
