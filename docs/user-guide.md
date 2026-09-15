# Job Apply Pro user guide

This guide applies to Reviewed Browser Submission Reconciliation `v0.78.0-alpha.1`. This is an alpha milestone, not a production-ready signed release. The active build adds a separately reviewed, read-only closure path for one response-lost exact Greenhouse final-submit click; it never retries submission and accepts only a fresh same-origin, changed-page, identifier-backed provider confirmation. The inherited upload, navigation, field, profile, restore and portal safety boundaries remain unchanged. Named portal capability is disabled by default and is not a live compatibility claim. Select one durable workflow in the queue; the guide and all application selectors follow that workflow's candidate, application, portal, challenge, and communication records. For an imported public Greenhouse job, complete requirements, qualification/eligibility, and immutable resume review until status is **ready**. Choose **Review Greenhouse launch**, verify the exact URL, origin, document version, and fingerprint, then choose **Open reviewed Greenhouse application** and approve the cancel-default native dialog. The backend revalidates everything and derives the URL. When a recognized Greenhouse form page is captured, the supervised-session card shows the current stage, required controls satisfied, field/upload/manual blockers, the unique next control when present, and each expected postcondition. Native-field entry, one narrowly reviewed single-select widget, required resume upload, ready one-stage navigation and manual handoff retain separate exact reviews. At the reviewed final page, final submission remains a separate default-off, native-confirmed action and only identifier-backed provider confirmation is success. This build still does not bulk fill, log in, solve MFA/CAPTCHA or assessments. Backend allowed actions and exact review fingerprints remain authoritative. An `UNCERTAIN` result is never permission to retry blindly. Live providers, signed installers, physical Windows behavior and protected integrations retain their separate acceptance gates.

## Guided selected-application workspace

Select a row in **Durable workflow queue** before reviewing or changing an application. The **Guided application workspace** shows that application's candidate, saved backend state and application ID, then links to job/readiness, documents/evidence, application/fields, challenges and follow-up. Counts and statuses describe currently loaded records; they are not completion claims. **Suggested** identifies a useful section to inspect, not an authorized action.

Changing the queue selection also changes all **Target application** selectors and clears previews created for the previous application. Wait for the selected candidate/application details to reload before reviewing them. A Reference ATS run, supervised portal run or confirmation action is shown only when it belongs to the selected workflow. Communication counts likewise include only records correlated to that workflow.

If the selected browser has an unresolved external effect, use the guide's Operations link and inspect the preserved evidence. Do not repeat the action merely because it is absent from the current page. The guide cannot retry or clear that effect; an uncertain result remains consumed until a provider/browser-specific reconciliation contract proves a safe outcome or the workflow is handed to you.

For an eligible uncertain field write, Operations shows **Verify current field outcome** only when the exact browser session still exists. Leave the browser on the unchanged page in user takeover and make sure the intended value is visibly present. Choose the button to request a read-only preview, then inspect the native warning. **Cancel** is the default. **Record verified outcome** causes the backend to perform the same read-only proof again and record local evidence; it does not type, select, check, click, navigate, upload, submit, or retry. A moved or changed page, mismatched value, unavailable worker, stale preview, older uncertain record, or unsupported action remains unresolved. The original `UNCERTAIN` history is retained, and the browser stays in takeover until you separately choose to resume it.

For an eligible uncertain reviewed Greenhouse stage-navigation click, Operations instead shows **Verify current form stage**. Leave the visible browser at the result page in user takeover. The backend must independently observe the same portal origin and a recognized, strictly later non-confirmation stage with a different page fingerprint. Inspect the cancel-default native warning and choose **Record navigation outcome** only if the displayed transition is expected. The backend observes and proves the page again before recording reconciliation. It does not click, navigate, upload, submit, or retry; confirmation pages and same/earlier/unknown/foreign-origin pages remain unresolved. The original action and attempt stay `UNCERTAIN`, and resuming automation remains a separate deliberate action requiring a fresh capture.

For an eligible uncertain reviewed Greenhouse document selection, Operations shows **Verify current upload outcome**. Leave the visible browser on the same recognized upload stage in user takeover. The backend must independently observe the same origin, page type and form stage, a changed page fingerprint, and exactly one occurrence of the encrypted intent's filename. Inspect the Cancel-default native warning and choose **Record upload outcome** only if that local selection is expected. Approval repeats the full read-only proof. It does not restage a document, upload, navigate, submit or retry. An unchanged page, absent or duplicate filename, different stage/origin, stale review, unavailable worker or changed approval-time observation stays unresolved. The result proves only that the worker observed the expected filename; it does not prove provider receipt, bytes, retention, parsing, application attachment or submission. The original action and attempt remain `UNCERTAIN`; capture again before any separate resume.

For an eligible uncertain reviewed Greenhouse final-submit click, Operations shows **Verify confirmed submission**. Leave the visible browser on the provider confirmation page in user takeover. The backend must independently observe the same Greenhouse origin, a changed page fingerprint, the catalog's confirmation page and capability, required confirmation text, and one bounded provider confirmation identifier. Inspect the Cancel-default native warning and choose **Record confirmed submission** only if this is the expected application. Approval repeats the complete read-only proof and saves only a keyed identifier fingerprint; the raw identifier is not returned to the renderer. It never clicks, navigates, uploads, submits or retries, and the original action and attempt remain `UNCERTAIN`. The desktop then immediately performs the existing read-only supervised capture. If confirmation is still current, that capture records `SUBMISSION_CONFIRMED` and stops the run. If the page changes or capture fails after durable reconciliation, no submit is replayed: return the browser to the exact confirmation page and use the supervised run's ordinary current-page capture to complete the record.

Gemini image review accepts fully decoded, static JPEG, PNG, or WebP images matching the declared type. The app applies EXIF orientation and creates a clean PNG without embedded EXIF/GPS, comments, PNG text, thumbnails, XMP, or color-profile metadata. Original and normalized images must each fit 5 MiB, no edge may exceed 8,192 pixels, total pixels may not exceed 16,777,216, and each request allows four images. A compressed photo may exceed the limit when converted to PNG; the app rejects it instead of silently resizing it. Export a smaller image and review it again. Embedded color profiles are not applied and higher-bit-depth inputs become 8-bit RGB/RGBA, so compare the normalized visual result carefully. Metadata removal does not redact visible names, faces, text, or other sensitive pixels; review those before consenting. URL-based image parts are not fetched or normalized by this boundary.

Media is uploaded only after separate consent and used in a stateless interaction after the provider reports it active. Before each upload, the app commits durable cleanup intent; returned resource names are encrypted locally before other file metadata is validated. The app immediately attempts deletion, including after malformed metadata or inference failure. If finalization or deletion cannot be confirmed, the invocation fails and automatic retries/fallback stop. Unresolved cleanup blocks further media invocations using the same provider kind, trusted endpoint, and exact API key, including after restart or a provider-configuration rename. Treat every visual result as a proposal and compare it with the source image before promoting any candidate claim.

Gemini can briefly report an uploaded image as processing. The app waits and checks only that exact uploaded file, sharing the configured request-time allowance across all images and the model response (at most 30 processing checks per request). Expiry or failed processing is not a successful response. Cleanup gets a separate, limited allowance; an uncertain upload or unconfirmed deletion remains visible in media recovery and blocks further use of that credential. These checks do not guarantee cancellation of an already-running network operation at an exact instant.

## Public Greenhouse discovery

In the Workbench, enter a public Greenhouse board token (the employer token, not a complete URL, API key or password). Choose **Preview public jobs**, select one posting and choose **Review selected job**. Read the employer, title, location, normalized description and source identity. Select the intended local candidate profile and review again if the profile changed, then choose **Import reviewed job locally**.

These explicit actions make public read-only requests. Candidate details and documents are not sent. The saved job is not evaluated or applied for, and mock advancement controls are unavailable. Repeating an unchanged import reuses its local workflow. If the posting changed since preview, review it again; if it differs from an already saved immutable snapshot, this release preserves that snapshot and does not offer replacement. Unsupported/custom URLs appear as text only; this panel opens no browser. Read the original employer posting before any later application decision.

## Review saved job readiness

Select an imported Greenhouse application in the queue and open **Reviewed job readiness**. Choose **Load saved job evidence**, read the exact source lines and classify selected requirements as mandatory, preferred or ambiguous. Preview and approve the requirement set. The app does not infer missing employer requirements or certify that your selection is complete.

For every requirement, review a supported, contradicted or unknown finding. Supported/contradicted findings need current locked claims approved for applications from the same candidate profile. Unknown findings have no asserted evidence. Missing, corrupted or superseded source documents cannot support a claim.

Review coverage separately from eligibility. No mandatory criteria, any ambiguous criterion or unsupported mandatory evidence prevents eligibility clearance. Saving an assessment is not permission to continue; explicitly approve eligible findings before selecting a resume. Then preview the recommendations and approve one exact immutable version in the native dialog.

Changes to requirements, claims, source evidence, resume metadata or bytes require fresh review. A historical **Documents selected** state may remain after current readiness becomes **Stale**; it is not current upload authority. This panel never opens, fills or submits an application. Other portals and saved-source replacement remain unsupported by this review slice.

## Install and start

The packaged browser runtime includes `resources/backend/job-apply-pro-browser-worker.exe`. Do not delete, rename or replace it independently. The app launches it hidden in an isolated profile; it does not use an existing personal browser profile or system Python. If the worker is missing or cannot start, repair/reinstall the matching complete package. Do not download a similarly named executable from another source. Normal packaged operation uses installed Microsoft Edge; automated package tests use controlled Playwright Chromium and local fixtures. Those tests do not validate real portals.

When explicitly using Chromium, its matching Playwright browser must already be installed. Frozen Windows workers use `%LOCALAPPDATA%\ms-playwright` by default and preserve an explicit `PLAYWRIGHT_BROWSERS_PATH` override. No browser is downloaded automatically by the app; a missing executable is a recoverable installation/configuration error, not permission to use another personal browser profile.

1. For production use, wait for a published signed installer. The local `Job-Apply-Pro-0.76.0-alpha.1-x64.exe` development-candidate filename does not prove signing or successful acceptance. Consult the readiness audit for the exact version's build, signature status, hashes, and limitations. Test unsigned candidates only on an isolated development workstation.
2. For a future signed release, compare the Authenticode publisher and checksum with its release record; do not assume that a GitHub account name is the certificate subject. Do not proceed with production installation if its signature is invalid or its publisher is unexpected.
3. Choose a per-user installation directory and start Job Apply Pro.
4. The first start creates an OS-protected encryption key, migrates the local database, and starts the bundled loopback backend. Python and Node are not required.

The packaged browser runtime uses Microsoft Edge. Keep Windows and Edge supported and updated.

## Startup, shutdown and restore safety

Only one desktop instance owns the workspace; starting a second instance focuses the first. Startup waits for migration and authenticated backend readiness. Quit and update wait for the app's owned backend processes to exit instead of treating a termination request as success.

Offline restore changes several files. If it exceeds the two-minute observation window, the app does not kill its writer. Keep the app open and preserve the original key, backup, staged files, database, document directory and complete `restore-control` directory. Quit, update and restart are blocked while a restore may still write. The on-disk guard survives app restart and continues to block normal backend/desktop startup until authenticated terminal evidence is finalized.

V2 restore evidence retains exact encrypted before/after images for every target. On the next packaged start, an active guard sends Job Apply Pro into an isolated native recovery-only session before migrations, the API, updates or the normal window can start. The app loads only the existing OS-protected key, authenticates the exact guarded operation through the bundled backend and shows a native warning; the key and recovery evidence never enter the renderer.

**Keep workspace blocked** is the default and safest choice when you are unsure. For an initially interrupted v2 operation, inspection provides distinct fingerprints for **Roll back exact restore** and **Resume exact restore**. Rollback returns only that operation's targets to sealed pre-operation bytes. Resume installs only the same operation's retained encrypted after-images; it does not reread staging or backup files, open restored SQLite content, or merge later work. Once either action is published, the opposite choice disappears and cannot be substituted after a restart. Both paths skip exact completed targets, keep the database last, require a matching terminal receipt and reinspection, clear the guard only after verification, and close so you can reopen normally. For an authenticated terminal `APPLIED` or `ROLLED_BACK` receipt, **Finalize exact restore state** only verifies terminal targets and clears the guard. Unknown target bytes remain blocked. Legacy v1 evidence remains completion/manual-recovery only.

Do not delete the guard, evidence objects or SQLite sidecars, fabricate a receipt/fingerprint, create a replacement key, export the protected key for a manual command, or install an older build to bypass admission. If the native inspection fails, times out, reports legacy/unknown evidence, or detects independently changed targets, it leaves the workspace blocked; preserve everything and stop for qualified manual recovery. This recovery path has passed exact v0.62 schema-0028 backend-dist/delivered-package and delivered recovery-protocol tests, but remains alpha until protected CI/security and physical installed-app `safeStorage`, native-dialog, sleep/restart and interruption validation is recorded.

If shutdown cannot be verified, the app keeps or reopens its window. Do not force-close processes or remove recovery files to bypass this warning.

## Review durable media recovery

Open **Operations, recovery & licensing** and find **Durable media recovery**. Select **Refresh media cleanup** to read unresolved local records. Refresh does not contact the provider. The panel shows operational record IDs, provider labels, states, attempt counts, safe reasons, and relevant times; it does not show image bytes, hashes, remote resource names, URLs, API keys, or filenames.

Known-resource recovery runs at backend startup and periodically while it is running. Each pass attempts at most two eligible deletions, with 60 seconds between background passes and a 15-second configured network timeout per deletion. Active uploads and interactions retain a 20-minute lease renewed between lifecycle phases. A restarted worker waits for an unexpired lease; neither the lease nor the network timeout is a guaranteed real-time cleanup deadline. Failed deletions remain pending with backoff. Only provider responses `200`, `204`, or `404` are accepted as deletion confirmation; a pending/accepted response is not enough.

- **Active lease / awaiting recovery:** the upload or interaction may still own the resource. Review the displayed lease time and refresh later; a retry does not override an active lease.
- **Deletion pending:** select **Retry automatic deletion** to run an eligible deletion-only pass. It does not bypass retry timing, upload media, run a model, or list the provider's files. Automatic deletion requires an enabled Gemini configuration with the same trusted endpoint and exact original API key; a renamed or aliased configuration with that credential identity can recover the record. Changed or missing credentials leave the obligation unresolved. Different API keys do not prove the same remote account, and rotating a key does not clear earlier cleanup obligations.
- **Unknown resource — manual review:** the app cannot safely identify what the provider retained after an uncertain upload. Inspect the original provider account yourself and verify that its media cleanup is complete. Only then select **Review manual cleanup**, type exactly `I VERIFIED PROVIDER MEDIA CLEANUP`, and select **Record operator acknowledgement**. This records your verification and closes the local obligation; it is not independent app confirmation of remote deletion. If the record changed since review, acknowledgement fails: refresh and review again.
- **Provider review required / unreadable encrypted metadata:** the retained resource cannot be recovered safely. Known encrypted-resource records cannot be manually acknowledged away, even after provider review. Preserve the database and original encryption key and seek support; do not delete records or replace the database to bypass the block.

Recovery does not guarantee provider deletion and cannot safely guess an unknown resource. Keep API keys in local secret configuration only; never put them in chat, diagnostics, screenshots, or a support report. No unresolved local records means no outstanding journal entries, not a complete inventory or audit of the provider account.

## Review unresolved external effects

Open **Operations, recovery & licensing** and find **External effects requiring attention**. The count includes local browser actions and AI completion/embedding calls that are `PREPARED`, `DISPATCHING`, or `UNCERTAIN`. The list is read-only and shows at most the 20 newest safe records: effect kind, bounded subject reference, state, attempt count, safe error, and timestamps. It never displays a prompt, candidate fact, page content, provider response, credential, token, request fingerprint, or native idempotency key.

- **Prepared:** no dispatch was recorded. Preserve the existing claim and inspect local evidence before deliberately starting anything new.
- **Dispatching:** the call crossed the dispatch boundary without a terminal local result. Do not retry while its outcome is unknown.
- **Uncertain:** the app cannot prove whether the remote action happened. Inspect the named provider or use browser user takeover before deciding on a separately reviewed new action.

There is intentionally no generic retry, clear, or resolve button. Removing a record would erase replay authority, while blindly retrying could duplicate an external action or cost. A zero count means no unresolved records are present in this ledger; it does not prove that every external provider account has been audited.

## Review and enable notifications

The **Actionable notifications** panel always shows current local action alerts. It covers sign-in verification, CAPTCHA and other user intervention, approaching assessment deadlines, stopped or expired workflows, recruiter/interview/offer messages, due follow-ups, upcoming synced interviews, backup failures, and update failures. Select an in-app alert to move to the relevant workflow, challenge, communication, or operations section. Calendar reminders use generic 24-hour and one-hour wording and never expose the event title, participants, provider identifier, location, or meeting URL.

Native Windows delivery is off by default. Select **Enable** in the notification panel to opt in. The preference and stable delivered-event identifiers are stored in a bounded local state file; message bodies and account details are not stored there. The app checks once per minute, retains at most 50 active alerts, and shows no more than five new native alerts during one refresh. Selecting a Windows notification focuses Job Apply Pro and opens a fixed workbench section.

Notification wording is intentionally generic. Windows can display notifications on a locked screen or retain them in Notification Center, so native text never includes employer or job names, candidate data, message senders or subjects, follow-up reasons, diagnostics, passwords, tokens, or security codes. If Windows notifications are unavailable or disabled, in-app alerts continue to work. Use **Disable** to stop future native delivery. Windows Focus Assist, locked-screen display, click activation, and sleep/resume behavior remain part of the physical release-lab checklist.

## Connect email and calendars

Job Apply Pro does not accept mailbox passwords. Each provider connection uses the system browser, OAuth Authorization Code with PKCE, a one-time loopback callback, and encrypted local token storage.

After a Google Calendar or Outlook Calendar connection reports read access, select **Sync calendar**. The app reads events from one day before the current time through 60 days ahead, stores sensitive event details in the encrypted local database, removes events no longer returned within the refreshed snapshot, and reports only counts and the window end date. Calendar synchronization is manual in this build; there are no background provider webhooks or push subscriptions. The notification check reads the local snapshot once per minute and does not create additional provider traffic.

When the same connection also has the provider's reviewed calendar-write scope, open **Reviewed calendar event creation**. Choose the bound provider and enter the exact title, start, end, IANA time zone and optional plain location. This release always creates the event with private visibility, busy availability and provider-default reminders disabled. It does not accept attendees, invitations, conference links, recurrence, provider event IDs or updates. Choose **Prepare exact review** and read the saved provider, account, primary-calendar target, values, fixed policies and review SHA-256. If any value or account is wrong, discard the plan and prepare another one; do not create it and edit remotely as a substitute for review.

Choose **Review & create with native approval** only once. The native dialog refetches the plan and again shows the bound provider/account, target, event values and fixed private/busy/no-reminders/no-invitations policy; **Cancel** is the default and sends no create. After approval, that plan is permanently consumed even if the provider rejects it, the response is lost, the app closes or the outcome is uncertain. **Confirmed** means the provider accepted one request and returned a valid identifier—it does not prove delivery or readback. For **Planned** or **Uncertain**, inspect the exact bound provider calendar before doing anything else and never retry that plan. For **Failed**, the provider path reported a definite non-application, but the plan is still closed; inspect the calendar before manually preparing a distinct replacement. The app never creates calendar events in the background.

Before **Review & connect** becomes available, the owner must register a public desktop application with the provider. Create a local JSON file containing its public client ID and reviewed scopes, then select **Import provider config**. Job Apply Pro validates a maximum 64 KiB file, shows only provider/scope/capability and automatic-category details in the native confirmation, and encrypts the accepted registration metadata in the local database. Import replaces the current local registration. The raw JSON and client IDs never enter the renderer. Passwords, access tokens, refresh tokens, and client secrets are invalid and must not be included.

Managed deployments may instead set `JAP_COMMUNICATION_CONFIG_JSON`; that environment value takes precedence and disables desktop replacement/clearing. Do not put a real configuration file, tokens, passwords, or private account data in Git, GitHub Actions, the Google development document, or chat. A minimal local import has this shape:

```json
{
  "oauth_clients": [
    {
      "provider": "GMAIL",
      "client_id": "registered-public-desktop-client-id",
      "requested_scopes": [
        "openid",
        "email",
        "https://www.googleapis.com/auth/gmail.readonly"
      ]
    }
  ]
}
```

The repository also includes `docs/examples/provider-configuration.example.json` with read-only examples for all four providers. Copy it outside the repository, replace only public desktop client IDs, remove unused providers/scopes, and import the copy. Add write scopes only when you intend to review and use the corresponding write operation.

For Google:

1. Create or select a Google Cloud project, enable the Gmail and/or Calendar APIs, configure the OAuth consent screen, and create an OAuth client of type **Desktop app**.
2. Register the loopback redirect `http://127.0.0.1:8765/api/v1/communications/oauth/callback`.
3. Request only the capabilities in use. This build allowlists `gmail.readonly`, `gmail.send`, `calendar.readonly`, and `calendar.events`, plus `openid` and `email`.
4. Review Google's [desktop OAuth flow](https://developers.google.com/identity/protocols/oauth2/native-app), [Gmail scope classifications](https://developers.google.com/workspace/gmail/api/auth/scopes), and [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth). Gmail read access is currently a restricted scope and public distribution may require Google verification and an independent security assessment.

For Microsoft:

1. Create an app registration in Microsoft Entra, configure it as a public desktop client, and add the same loopback redirect URI.
2. Add only delegated Microsoft Graph permissions in use: `User.Read`, `Mail.Read`, `Mail.Send`, and/or `Calendars.ReadWrite`, with `openid`, `email`, and `offline_access` for sign-in and refresh.
3. Review Microsoft's [authorization-code/PKCE flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow), [desktop app registration guidance](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration), and [Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference). An organization may require administrator consent.

After configuration, select **Review & connect**, verify the provider host and displayed scopes, sign in manually, complete any MFA, and approve only the expected access. Return to Job Apply Pro and refresh the dashboard. Use **Revoke access** to revoke at the provider where supported and always delete the encrypted local credential. Microsoft may also require revocation from the account's application-consent page. **Clear config** disables local provider registrations but does not revoke provider consent or delete retained encrypted OAuth tokens; revoke each connection first when removing access.

For a connected Gmail or Outlook account with read access, select **Sync messages**. The first operation establishes encrypted provider state; later operations request only newly added Gmail history or newly created Outlook Inbox messages. A result identifies the operation as initial, incremental, or recovery and reports fetched, newly imported, and already-present counts. If Gmail expires a history ID or Microsoft requests a delta reset, the app performs one bounded recovery enumeration. The cursor advances only after all returned messages are durably processed, so an interrupted import safely replays provider IDs on retry. Reauthorizing a different account invalidates the prior account binding.

The app follows at most ten provider pages and imports at most 1,000 messages per operation. Repeat provider message IDs reuse the existing encrypted record. Gmail attachment filenames come from bounded MIME metadata; Outlook attachment filenames are requested separately only when the message reports attachments. Inline resources are ignored, attachment bytes are never downloaded, and filenames do not authorize opening or trusting a file. Provider errors, repeated page tokens, an off-origin Microsoft continuation or delta URL, or a resource limit stop the sync without treating incomplete data as complete. Cursor contents remain encrypted and never appear in the interface, diagnostics, logs, or exports. Webhooks/push notifications are not enabled by this build.

## Review email and attachments

Open **Reviewed email & verified attachments**, refresh correspondence/drafts and explicitly choose **New message** or **Reply**. Replies require freshly synchronized source metadata from the current verified account; recipient and subject are fixed to that reviewed source. New messages use explicitly entered recipient and subject. Offline previews can be saved but cannot send; connecting later requires a fresh draft. Attachment drafts require an owning workflow for profile verification; recruiter-first messages without one remain text-only. Select up to four immutable PDF/DOCX versions totaling at most 2 MiB. Supported roles are resume, cover letter, certification, education and portfolio; `OTHER` is unsupported. Files are not metadata-stripped or malware-scanned, so inspect originals first.

Check the exact recipient, subject, text, filenames, sizes and hashes. **Review & send with native approval** opens a separate confirmation dialog; cancel is the default. No attachment content or provider credential is exposed to the renderer. Reconnecting the account or changing reviewed files invalidates the old approval; create and review a new draft. Legacy unbound drafts also require a new review.

**Accepted** means the provider accepted the request, not that the recipient received it. Outlook acceptance does not return a message identifier. Reply threading has source-level serialization tests, not live mailbox-placement acceptance. Delivery and bounce reconciliation remain unimplemented. **Uncertain** or a lost send response must not be retried or bypassed by automatically recreating the message; inspect the provider account and recorded audit first. Each draft permits only one locally reserved attempt, including failures. A proven pre-dispatch review error allows another manual review only after a successful explicit refresh; it is distinct from an uncertain send.

## Generate and retain application documents

Import source resumes and supporting material in DOC, DOCX, PDF, RTF, TXT, or Markdown form. Review every proposed claim before approving it. Tailored generation ignores proposed, rejected, superseded, unlocked, or profile-only claims.

Before choosing a resume file, enter a clear variant label such as `Platform engineering`, optional comma-separated job-family tags such as `platform, cloud, security`, and whether the file should receive the primary-resume preference. These fields are local ranking metadata; they are not sent to a job portal.

To select a resume for an application:

1. Open **Explainable resume selection**, choose the target application, and optionally enter preferred tags.
2. Keep the primary preference enabled only if a primary resume should receive its documented 10% ranking factor.
3. Select **Rank resume variants** and review every candidate's percentage and reasons. The top row is advisory; you may choose any reviewed variant.
4. Select **Review & select**, then approve the native dialog. If the job, requirements, document versions, exclusions, or preferences changed, selection fails and you must rank again.

The application stores the exact immutable document-version ID and a durable audit of the score, reasons, criteria, and review fingerprint. Ranking is deterministic and local; it does not infer missing experience or prove eligibility. Keep seniority and industry wording in the job title, requirements, or your variant tags when those distinctions matter.

## Review application questions and drafts

Use **Application answer provenance** after creating an application. Select the application, enter the exact question as shown by the employer, provide a stable canonical field such as `work.authorization`, choose the answer kind, and copy the portal character limit when one is shown. For multiple choice, enter one exact allowed choice per line. Number/salary questions can have minimum and maximum bounds; date/availability questions can have earliest and latest dates. **Draft answer** first looks for a reviewed reusable answer for that field. Leave AI drafting disabled to record an unresolved question without invoking a model.

When governed AI drafting is enabled, the model receives only retrieved locked claims and limited job context. Check external-processing consent only when you authorize an externally configured provider; local routes do not require that consent. A generated answer must cite retrieved claims and always remains review-required. Read the displayed source, evidence IDs, provider/model/prompt identity, confidence, limits, and limitations.

Edit the text and evidence list, then select **Review & save** and approve the native dialog. Yes/no values normalize to `Yes` or `No`; numbers remove display punctuation and currency symbols; dates normalize to `YYYY-MM-DD`; and multiple-choice values must exactly match a recorded option. This saves an application-specific reviewed revision; it does not change locked profile facts. Use **Promote reviewed answer** only when the wording should become a locked reusable library entry. Promotion has a second native confirmation and rejects stale or unreviewed records. No operation in this panel signs into or submits to a portal.

## Review observed portal field bindings

After an application answer reaches Reviewed or Promoted state, capture the current supervised portal page and use **Observed portal field binding** to select a detected control. Job Apply Pro supplies its exact portal, page fingerprint, deterministic key, kind, label, options, required state, and visible constraints. Use manual sanitized entry only for an unsupported widget. Mark legal attestations and signatures explicitly.

Select **Preview exact binding**. Review compatibility errors, confidence, answer source and revision, validation rules, and the proposed automation permission. Select **Approve reviewed binding** only when the observed control and canonical answer are the same field. The native dialog and backend fingerprint bind the approval to that exact answer revision and observation. If either changes, preview again.

Enable `JAP_SUPERVISED_FIELD_EXECUTION_ENABLED=true` only for supervised use. On a fingerprint-current page, an `AUTOFILL_ALLOWED` native text/select/checkbox/radio binding offers **Review & populate exact field**. The desktop shows a native confirmation, the backend re-observes and revalidates the full binding, executes one verified action, records evidence without answer text, and returns control to you.

Native select answers must exactly match one current visible option label, including case. Hidden HTML option values are never accepted as reviewed answers. Duplicate visible labels remain manual because the selection would be ambiguous.

Radio options execute only when the reviewed answer exactly equals one unique visible option label and that option has the same exact semantic label locator. Duplicate or changed labels fail closed. Signature, disclosure, file-upload, disabled, custom-widget, and legal-attestation controls remain visible user work even after binding. This execution path never submits the application.

Legacy DOC and scanned-PDF support are opt-in because they invoke local document tools. Install LibreOffice and/or Tesseract from their official distributions, then configure exact absolute executable paths in the Windows user environment and restart Job Apply Pro. Do not enter command lines or portal credentials:

```text
JAP_DOCUMENT_LEGACY_CONVERTER_PATH=C:\Program Files\LibreOffice\program\soffice.exe
JAP_DOCUMENT_OCR_ENABLED=true
JAP_DOCUMENT_OCR_TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
JAP_DOCUMENT_OCR_LANGUAGE=eng
```

DOC conversion uses a disposable LibreOffice profile, fixed arguments, a timeout, and a bounded DOCX output that is validated and parsed again. OCR runs only on PDF pages without meaningful ordinary text, is limited to 25 pages by default, and displays extraction notes when pages are skipped or text remains incomplete. Treat OCR text as proposed evidence and compare it with the source image before approval.

1. Create or select an application whose job title and requirements have been persisted.
2. In **Candidate documents & evidence**, open **Tailored document review** and select the application.
3. Choose **Resume** or **Cover letter**, DOCX or PDF output, and a short variant label.
4. Select **Preview evidence**. Review the target employer/title, every selected claim, matched requirements, and the list of required requirements that remain unsupported. A missing requirement is a gap to review, not permission for the app to invent an answer.
5. Read every heading and paragraph in the exact document preview, then select **Review & generate exact document** only when it is correct. The native dialog approves the current review fingerprint; if claims or job requirements changed, generation stops and requires a new preview.
6. Choose a destination in the native save dialog if you want a usable DOCX/PDF copy. The decrypted bytes move only through the Electron main process to that destination and never enter the renderer.
7. The result remains stored as a new encrypted, non-primary candidate document version even if the save dialog is canceled. Select that exact version for the applicable workflow rather than assuming the newest document is always correct.

When a supported portal verifies the displayed upload filename and later observes an identifier-backed submission confirmation, it retains the exact document version, SHA-256 digest, role, and upload fingerprint with the application. This is evidence of which local file version was submitted; it is not a copy of a portal password, browser cookie, or employer response. If the portal filename or digest differs, retention fails closed and the submission must be reviewed manually.

New PDF imports preserve layout lines and use conservative column-major ordering only after repeated, well-separated columns are detected. A visible extraction warning tells you when this heuristic ran. New DOCX imports preserve paragraphs and tables in their top-level document order. Review complex graphics, nested tables, floating text boxes, unusual spanning rows, and OCR text against the source before approving claims. LibreOffice and Tesseract are not bundled; OCR language data must be installed locally; deterministic token matching remains conservative; and advanced visual templates are not yet implemented.

Tailored document review offers Professional and Compact templates. Deterministic local evidence ranking remains the default. Governed AI ranking is optional: select it for the preview, and separately check external processing consent only if you authorize an external configured route. Local AI routes do not need external consent. If the gateway is unavailable, blocked by policy, or returns an invalid ranking, the preview clearly reports deterministic fallback. Always review the displayed ranking method, exact paragraphs, selected evidence count, and missing requirements before choosing Review & generate exact document. Generation refuses a stale fingerprint and still opens a native confirmation dialog.

## Run a supervised portal validation

Supervised portal execution is intended for a bounded, owner-approved test window. It does not accept or store portal passwords. Before enabling a portal, the owner must review the provider's current terms, the account's authority, the planned actions, the exact origins, and the stop conditions.

For a development launch, configure only the portals being tested:

```text
JAP_AUTOMATION_ENABLED=true
JAP_SUPERVISED_PORTAL_ENABLED=true
JAP_SUPERVISED_PORTAL_ALLOWLIST=LINKEDIN
JAP_SUPERVISED_PORTAL_SUBMISSION_ENABLED=false
```

Restart Job Apply Pro after changing local environment configuration. Leave the submission gate false until a prepared application and the test authorization have both been reviewed.

1. In **Portal catalog & supervised execution**, choose the exact portal and enter its HTTPS start URL. Add only exact HTTPS origins needed for the same application flow; redirects to an unlisted origin stop automation and require review.
2. Enter a unique persistent profile name for this portal tenant/account. A saved profile card records only its browser engine, name, portal classification, and exact origin set. Reuse that exact spelling only with the same origin set; select a new name for another Workday/Taleo tenant, portal, or account. Job Apply Pro rejects case aliases and origin-set changes before browser startup.
3. Start the visible browser. Sign in directly inside that browser. Do not place a username, password, security code, or token in environment variables, source, documentation, chat, or the application notes. The browser may retain cookies in its local profile, but the app does not call the profile “logged in” or expose cookie contents.
4. Complete MFA, email codes, CAPTCHA, assessments, terms acceptance, legal attestations, and signatures yourself. Select **Capture current page** after each manual boundary so the app records a fresh fingerprint and classification.
5. Review the current URL, page type, intervention reasons, evidence count, and the complete application in the provider UI.
6. To test automated final submission, separately set `JAP_SUPERVISED_PORTAL_SUBMISSION_ENABLED=true`, restart, return to the same persistent profile, and capture the final review page again. Select **Review & submit exact application** only when the displayed application is correct. The native dialog is the last approval boundary.
7. Treat only an identifier-backed provider confirmation as confirmed. If the result is uncertain, the run records `SUBMISSION_UNCERTAIN`; verify directly in the provider account instead of retrying blindly.
8. Select **Stop & preserve trace** when complete. Remove the portal from the allowlist and disable both supervised gates after the approved window.

To remove one stopped profile's local cookies and browser state, find its saved-profile card and choose **Retire local profile data**. Review the native warning's exact engine, origins, retained-session count, file/directory counts, byte count, and fingerprint. Cancel is the default. Approving removes only the local browser profile; it does not erase Job Apply Pro history, log out server-side provider sessions, revoke the account, or securely overwrite storage media. After retirement, the card reports **Retired** and that historical profile name cannot be reused. Create a new unique name if you later start another session.

If v0.75 retirement isolates the profile but local cleanup fails, the saved-profile card reports **Cleanup pending**. Choose **Finish isolated profile cleanup**, review the exact profile metadata and remaining entry/byte counts in the new native warning, and approve only if they are expected. Cancel is the default. The backend rechecks the cleanup UUID, durable history, absent canonical profile, and current isolated inventory before removing anything. A changed, duplicate, aliased, unsafe, or restored target is rejected. Cleanup retains historical evidence and still does not log out the provider or securely overwrite the storage medium. Anonymous quarantine data left by an older v0.74 build requires manual support because it cannot be safely associated with one profile.

The application cannot prevent the account owner from manually clicking controls in a visible browser. Such actions remain the owner's actions; the evidence stream distinguishes captured user-driven state from an automated, fingerprint-approved submission.

### Review required-field coverage

After capturing an application page and choosing its local application record, select **Review required-field coverage**. The report includes required controls only and classifies each as ready, already verified, manual, unbound, stale, or ambiguous. Resolve unbound and stale mappings individually; handle manual controls directly in the visible provider page. The review does not decrypt answers, fill fields, or authorize submission.

Only controls with positive visibility evidence from the latest capture appear in detected-field selection or required-field coverage. Fields hidden by CSS or conditional layout are omitted until they become visible and you capture the page again. An observation created by an older build has no positive visibility evidence, so recapture it before reviewing coverage or executing an approved field.

`VALID ON PAGE` means only that the browser's native HTML constraints currently pass for that control. Job Apply Pro does not read the current value. Review the visible value yourself because native validity does not establish truthfulness, semantic correctness, provider-side acceptance, or submission.

Fields declared with `aria-required=true` are included in the checklist even when the portal omits native HTML `required`. They cannot show `VALID ON PAGE` from browser validity alone because the browser may not enforce the ARIA declaration. Resolve them through the normal reviewed binding, verified execution, or visible manual path.

Controls declared with `aria-disabled=true` are treated as disabled even when the DOM would technically allow a write. They are not offered for detected-field binding, appear as manual when required, and cannot run through approved execution. Capture again after the portal enables the control.

Controls labelled through `aria-labelledby` use the same normalized accessible name exposed to assistive technology. Job Apply Pro records whether a name came from ARIA or an HTML label and uses an exact role-and-name locator for the ARIA case. If referenced label text changes, the current observation or binding fingerprint changes and the field must be reviewed again.

If a portal marks a control `aria-invalid`, that field cannot show `VALID ON PAGE` even when its basic HTML constraints pass. Job Apply Pro records only a boolean invalid signal, not the value or validation message. Correct the field in the visible browser and capture again.

Native `readonly` and `aria-readonly=true` controls remain visible in the current observation but are not offered for detected-field binding. When required, they remain manual in coverage and cannot run through approved field execution. Review provider-managed content directly and capture again only after the portal makes the control editable.

If a control or its containing form declares `aria-busy=true`, Job Apply Pro treats the field as pending. It is not offered for binding, cannot show `VALID ON PAGE`, and cannot run through approved execution. Wait for the provider to finish validation and capture the page again.

Controls disabled by an ancestor `<fieldset disabled>` are treated as natively disabled even when the control itself has no `disabled` attribute. The standard first-legend exception remains enabled. Capture again after the provider enables the section.

Controls inside an HTML `inert` subtree remain visible for review but are not offered for binding, cannot show `VALID ON PAGE`, and cannot run through approved execution. Capture again after the provider makes the section interactive.

Controls inside an `aria-hidden=true` subtree remain visible in bounded review evidence but are not offered for binding, cannot show `VALID ON PAGE`, and cannot run through approved execution. Capture again after the provider exposes the section to accessibility tools.

## Safety model

- The desktop keeps profile and workflow data locally and encrypts sensitive values.
- Portal automation is untrusted input. A prepared application is not a confirmed submission.
- CAPTCHA, legal attestation, signature, and uncertain confirmation states require direct review.
- Catalog entries marked replay-tested or supervised-capable are not production-enabled integrations.
- A visible persistent browser profile may retain provider session cookies. Protect the Windows account, and stop using or remove the profile when the validation authorization ends.

## Back up and recover

Use **Operations, recovery & licensing** to create a verified backup. A successful backup is encrypted and checked at both the archive and entry level. Store a copy separately from the workstation, but never store the master key beside it.

Before restoring a database, review **Durable media recovery** and complete eligible deletion or verified unknown-resource manual review. Stop the backend and recovery worker, as the managed desktop does automatically. Offline restore requires an existing closed database: any SQLite `-wal`, `-shm` or `-journal` file blocks replacement before restore-specific database reads. Do not delete these files to force recovery. When storage is safely closed, unresolved cleanup obligations still block replacement; an older backup does not bypass that check.

Database restore preserves the complete compiled recorded-history dependency graph, including mail-send history. It rejects a backup that would remove or change any current recorded row or dependency, revive restored-only OAuth/session/cache state, fail encrypted/schema/relationship/document verification, or remove/change a send attempt or draft claim, including failed, uncertain and historical confirmed attempts. Use a verified complete backup containing the same current history; do not remove audits to force an older snapshot through. This prevents an old reviewed draft or revoked local authority from becoming usable again after restore.

To restore:

1. Verify the selected backup.
2. Select **Stage restore** and review the displayed fingerprint and file count.
3. Select **Apply staged restore** and read the warning.
4. Confirm only if the fingerprint is still the reviewed value. The app stops its backend and recovery worker, acquires exclusive workspace ownership, verifies closed storage and the complete reviewed archive/staged source before querying its SQLite data, then requires unresolved media cleanup and preservation of the compiled recorded-history/dependency graph, authenticated encrypted data and immutable documents. It compares one exact original-database byte snapshot before and after authorizer-confined in-memory bookkeeping, captures each plaintext target sequentially, records exact encrypted before/after images plus intent, and rechecks live targets before activating the persistent admission guard. The evidence remains under `restore-control/operations/<operation-id>/` and is subject to per-record, per-object, per-operation and global retained count/byte quotas.
5. Confirm the dashboard, candidate records, and backup status are expected before continuing work.

Successful completion verifies a receipt against the final files before removing the guard, migrating if required and restarting. If recovery is interrupted, startup and updates remain blocked even after a desktop restart. Reopen the same packaged app to enter its native recovery-only session; cancel unless the authenticated exact rollback or finalization choice matches your intent. Preserve the workspace, encrypted backups, original master key and every `restore-control` record. Do not repeatedly restore, delete the guard or generate a replacement key. A missing key for an existing workspace is not automatically replaced.

The backend commands `restore-status`, `restore-inspect`, `restore-rollback` and `restore-finalize` define the strict recovery protocol and remain useful for controlled development tests. Installed-user recovery is mediated by the native main process so the existing protected key does not need to be exported or pasted into a terminal. Finalization cannot resume incomplete writes or roll back files. Recovery requires a supported app-owned local layout; external/redirected or cloud-synchronized layouts are not validated. Follow the release runbook, [ADR-0066](adr/0066-durable-restore-admission.md) and [ADR-0071](adr/0071-durable-restore-rollback.md) before attempting manual recovery.

## Diagnostics

Select **Export diagnostics** and choose a destination. The JSON package contains build/runtime versions, counts, health states, byte totals, error classifications, safe context key names, and trace file metadata. It does not contain candidate content, error values, credentials, tokens, full paths, screenshots, trace contents, or browser cookies. Review the file before sharing it.

## Updates

Select **Check for updates**. Available updates are downloaded only after **Download update** is selected and installed only after **Restart and install** is selected. The app rejects publisher-signature failures and version downgrades. Back up before updating. If an update is not accepted, keep the current version and export diagnostics.

## Getting help

Include the application version, Windows version, steps to reproduce, and the reviewed diagnostic export. Never send resumes, passwords, provider tokens, database files, browser profiles, or unredacted screenshots through a public issue.
