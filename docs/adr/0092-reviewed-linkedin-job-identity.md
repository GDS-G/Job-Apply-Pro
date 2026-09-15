# ADR-0092: Reviewed LinkedIn job identity

- Status: Accepted
- Build: Reviewed LinkedIn Job Identity `v0.82.0-alpha.1`

## Context

The supervised browser can already classify a LinkedIn job-detail page and can navigate to a backend-reviewed direct link, but the desktop previously had no narrow way to display the stable identity of the exact captured job. Treating arbitrary page text as a job import would grant unbounded scraping and persistence authority. Trusting a renderer-supplied title or identifier would also separate the displayed identity from the backend-reviewed browser evidence.

## Decision

Browser observation records at most 50 visible `h1`, `h2`, and `h3` elements. Each record contains only its numeric level and whitespace-normalized text bounded to 300 characters. The ordered bounded heading records participate in the page fingerprint. Password controls remain excluded, and this heading inventory does not create generic extraction authority.

`SupervisedPortalService.review_linkedin_job_identity` accepts only an active LinkedIn run whose browser session remains in `USER_TAKEOVER`, whose stored current match is the exact `JOB_DETAIL`/`JOB_EXTRACTION` classification for the current fingerprint, and whose fresh read-only observation still has the stored URL and fingerprint on an allowed origin. The URL must be HTTPS on `linkedin.com` or `www.linkedin.com`, use no credentials, query, fragment, or nondefault port, and match exactly `/jobs/view/<positive decimal id>`. The observation must contain exactly one visible H1 with a normalized title no longer than 200 characters.

The returned immutable review binds policy version, run, browser session, exact canonical source URL, external job ID, title, page fingerprint, and observation timestamp into a SHA-256 review fingerprint. The authenticated API exposes a GET-only endpoint. The sandboxed desktop bridge accepts only the run UUID, and the renderer refuses a result whose run, browser session, or page fingerprint differs from the selected captured page.

## Consequences

The desktop can show a user-verifiable LinkedIn job title and ID without clicking, typing, logging in, importing a job, persisting page text, or claiming provider compatibility. Changed pages, query-bearing tracking URLs, fragments, alternate paths, ambiguous headings, unsupported sessions, and unrecognized pages fail closed. No schema migration is required. Controlled fixtures establish only the local contract; LinkedIn production automation remains disabled, `live_validated_page_types` remains empty, and authorized legal/terms and live-provider acceptance remain separate gates.
