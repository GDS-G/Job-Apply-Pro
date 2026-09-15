# ADR-0090: Reviewed browser link navigation

- Status: Accepted
- Build: Reviewed Browser Link Navigation `v0.80.0-alpha.1`

## Context

Supervised non-Greenhouse portals expose ordinary anchors while the browser is in user takeover. The renderer previously displayed observed controls but had no bounded way to continue through an ordinary job-detail or application-page link. Clicking the DOM element would also execute page listeners, JavaScript URLs, downloads, form behavior, or other provider-controlled side effects that cannot be represented by one exact recovery contract.

Link observations may contain tracking tokens, fragments, or user information embedded in a URL. Those values must not become renderer, log, API, or documentation data. A reviewed link must not inherit authority from a label or renderer-supplied URL.

## Decision

The browser worker records a bounded anchor target plus separate booleans for query, fragment, embedded-credential, and download presence. Normalization strips query values, fragment values, usernames, and passwords before the observation leaves the backend domain boundary.

`SupervisedPortalService._reviewed_link_candidates` derives candidates only from one uniquely keyed, visible, enabled, non-busy, non-inert, accessibility-visible native `a` element. Greenhouse uses its dedicated form contract and is excluded. Query-bearing, fragment-bearing, credentialed, download, non-HTTP(S), already-current, overlong, foreign-origin, cross-portal, and ambiguous targets receive no candidate.

Preview accepts only the run identifier, control key, and current page fingerprint. The backend reobserves the takeover session, proves the candidate again, and creates a SHA-256 review fingerprint over policy version, run/session/portal, allowed origins, source URL/origin/page type/fingerprint, control identity/label, and exact normalized target URL. The public preview exposes the target origin and path, never a query, fragment, credential, or renderer-chosen URL.

Electron owns a Cancel-default native confirmation. Approval sends only the immutable backend preview identifiers and review fingerprint plus the fixed `NAVIGATE REVIEWED LINK` phrase. The backend reobserves after resume and reproves the same review and target before dispatching one standard `NAVIGATE` with exact `URL_EQUALS`. It never clicks the DOM anchor. A redirect, changed page, changed target, changed review, or failed verification becomes intervention. An uncertain worker response is never retried and remains governed by ADR-0089 exact-URL reconciliation.

## Consequences

Users can advance through proven ordinary same-portal links without granting generic click authority. Sites whose navigation depends on query parameters, fragments, JavaScript handlers, downloads, cross-origin transitions, or ambiguous duplicate controls remain manual. This release does not claim compatibility with any live provider and does not enable production portal automation.
