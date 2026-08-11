# ADR-0023: Supervised portal execution policy

- Status: Accepted
- Date: 2026-08-11
- Build: Supervised Portal Execution `v0.14.0-alpha.1`

## Context

The portal catalog and replay corpus identify named job sites, while the Reference ATS proves a deterministic loopback submission. Neither boundary authorizes live execution. A live browser path must preserve user control, exact-origin restrictions, challenge intervention, step evidence, and a distinct final-submit decision without treating account passwords or a browser session as production authority.

## Decision

Add a supervised generic execution service behind two default-off gates: external browser automation and supervised portal execution. A named `PortalKind` must also appear in the local allowlist. The service launches a visible persistent browser, records append-only fingerprint evidence for the initial page and each captured manual step, and classifies the current page through the portal catalog.

Login, MFA, CAPTCHA, assessment, unrecognized/site-changed pages, legal attestations, and signatures remain manual. Final submission is a separate third gate. It requires the current review fingerprint, an Electron-native confirmation, the exact phrase `SUBMIT APPLICATION`, and exactly one unambiguous submit control. Confirmation is accepted only when the catalog's confirmation page/text rules and an identifier all pass; otherwise the result is `SUBMISSION_UNCERTAIN` and returns to user takeover.

No portal catalog entry is marked `production_enabled`, and no live-validation claim is added by source implementation alone.

## Consequences

- Supervised sessions can exercise named portals without consuming passwords from source, chat, CI, or documentation.
- Exact origins, persistent profiles, screenshots, traces, current-page fingerprints, and append-only step evidence make operator review and diagnosis possible.
- Ordinary page capture cannot grant final submission.
- Authorized live fingerprints, portal terms approval, rate limits, and regression evidence remain external gates before production enablement.
- Site-specific automated field mapping and document generation remain separate source work.
