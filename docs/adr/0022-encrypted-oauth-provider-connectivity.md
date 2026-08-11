# ADR-0022: Encrypted OAuth provider connectivity

- Status: Accepted
- Build: Provider Connectivity `v0.13.0-alpha.1`

## Context

The communication domain already normalized provider data, required explicit mutation confirmation, and persisted drafts and audits safely, but live provider implementations were disabled fixtures. The application needs Gmail, Outlook, Google Calendar, and Outlook Calendar without accepting or retaining account passwords. A desktop system-browser flow also cannot safely receive the authenticated local API header on the provider redirect.

## Decision

Use OAuth 2.0 Authorization Code with PKCE and the operating system's external browser. Provider registrations contain only public client identifiers, loopback redirect URIs, and reviewed scopes. Authorization state is high entropy, valid for ten minutes, hashed at rest, single use, and paired with a context-encrypted PKCE verifier. The loopback callback is the only privileged API route that does not require the desktop API header; its one-time state is the callback capability.

Persist access and refresh tokens only in context-encrypted database rows protected by the desktop-managed local master key. Expose only opaque credential references, account hints, granted scopes, status, and expiry. Refresh tokens before expiry, preserve rotated references, and fail closed when authorization, refresh, response shape, scope, or identifier validation fails.

Implement official HTTP adapters behind the existing provider protocols. Gmail and Microsoft Graph mail adapters normalize messages and return provider identifiers for reviewed sends. Google Calendar and Microsoft Graph calendar adapters normalize timezone-aware events and return provider identifiers for confirmed create/update mutations. The existing service-level fingerprint and idempotency audit remains authoritative.

## Consequences

The source can execute official provider APIs after registration and user consent without password automation or renderer-visible tokens. Google restricted/sensitive scopes and organizational Microsoft permissions may still require provider verification or administrator consent. Live-provider validation, provider terms approval, client registration, and production UX evidence remain external gates. The app must continue to request the narrowest scopes and must never reinterpret a configured client as user authorization.
