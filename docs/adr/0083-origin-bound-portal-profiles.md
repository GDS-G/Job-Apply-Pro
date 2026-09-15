# ADR-0083: Origin-bound portal profiles

- Status: Accepted
- Date: 2026-09-15
- Build: Origin-Bound Portal Profiles `v0.73.0-alpha.1`
- Storage schema: unchanged at `20260915_0030`

## Context

The supervised browser already uses visible persistent Chromium/Edge profiles. A user can sign in directly and the browser profile may retain provider cookies without Job Apply Pro receiving a password. Historical browser sessions persist the engine, profile name and exact allowed origins, but session creation previously checked only whether the same case-sensitive name was currently active.

On Windows, profile directories are case-insensitive. Names such as `tenant-a` and `TENANT-A` therefore resolve to the same storage location even though the application treated them as different. A stopped profile could also be reopened with a different origin set, allowing one persistent cookie jar to accumulate unrelated portal tenants or accounts without an explicit boundary. The desktop accepted a generic default name and did not show the existing portal/profile/origin relationship for deliberate reuse.

## Decision

`BrowserRuntimeService.create_session` normalizes the complete requested origin set before allocating a session, directory or worker process. It reads all historical browser-session snapshots for the same engine and case-insensitive profile name.

- Any `STARTING`, `ACTIVE`, or `USER_TAKEOVER` match remains an in-use conflict.
- A case-insensitive alias must use the exact previously stored spelling; a second filesystem identity is not created.
- All historical sessions for the profile must have one identical sorted origin set. Conflicting legacy history fails closed.
- A requested set that differs from the historical set is rejected with instructions to use a new profile name.
- Reuse with the exact engine, spelling, and normalized origin set remains allowed, including a different path on the same origin.
- Engine namespaces remain separate because they use different browser storage roots.

The first allocated session establishes the binding even if later worker startup fails. This is conservative: once a directory and durable session record exist, another tenant must use another name instead of assuming the failed start created no browser state.

The desktop derives saved portal-profile cards by joining the already authenticated browser-session and supervised-run responses in memory. It groups on engine plus case-insensitive profile name, treats inconsistent profile spelling, portal classification, or origin history as non-reusable, and shows at most the 12 most recently used groups. The generic Edge launch form offers only consistent non-Greenhouse Edge names through a datalist; the reviewed Greenhouse launch keeps its separate authority. The UI tells the user to reuse a name only with the same portal and exact origin set and to choose a new name for another tenant or account.

No login-success field is inferred or stored. A saved profile is evidence only of a local browser storage identity and its origin boundary, not proof that a provider account is authenticated. Passwords, one-time codes, cookies, tokens, and email addresses are not returned by this contract. Login, MFA, CAPTCHA, terms, legal attestations, signatures, and assessments remain visible user actions.

## Security and failure boundaries

- Origin binding is checked before a new session row, profile directory, artifact directory, or worker call.
- Binding comparison uses normalized exact origins, including scheme and explicit port; a subdomain or alternate Workday/Taleo tenant is a different origin.
- Active-profile exclusion and historical binding apply across workflows.
- A legacy case alias or multiple-origin history cannot be silently repaired; use a new unique profile name and retire the ambiguous profile manually.
- The renderer cannot change the backend rule. Datalist suggestions are convenience only; backend admission remains authoritative.
- This change does not inspect, export, synchronize, encrypt separately, or claim control over browser-managed cookies.
- Local sanitized tests do not establish live Workday, Taleo, LinkedIn, Indeed, or other portal compatibility or permission under provider terms.

## Consequences

- Workday and Taleo users can keep one clearly named browser profile per tenant/account and sign in manually without putting credentials into Job Apply Pro.
- Accidental reuse of one Windows profile directory across different exact origin sets is blocked.
- Existing consistent session history becomes visible and reusable without a schema migration or new credential store.
- Users who intentionally need another account on the same origin should create a distinct profile name.
- Removing or retiring browser profile data remains an explicit future lifecycle feature; this milestone only prevents unsafe reuse and surfaces existing records.

## Alternatives rejected

- Storing portal usernames/passwords would create an unnecessary credential vault and bypass provider-native login/MFA controls.
- Treating differently cased names as distinct is unsafe on the Windows filesystem.
- Binding only the current active session would allow unsafe reuse after a stop or crash.
- Automatically widening a saved origin set after a redirect would let hostile or changed navigation expand persistent-profile authority.
- Calling a saved profile “logged in” would claim authentication that the local application cannot prove.
