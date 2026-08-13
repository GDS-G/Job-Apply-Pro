# Job Apply Pro user guide

This guide applies to Sanitized Regression Corpora `v0.49.0-alpha.1`. This is an alpha build: named portal capability is disabled by default and is not a production compatibility claim. Native Windows notifications are source-complete but still require physical release-lab validation. Live mail/calendar access remains unavailable until the owner registers an OAuth desktop client, imports reviewed registration metadata, and completes provider authorization. Live Gemini access likewise requires an owner-created API key, reviewed provider terms/privacy/retention settings, explicit external-AI consent, and a local uncommitted gateway configuration.

## Install and start

1. Download the signed `Job-Apply-Pro-0.33.0-alpha.1-x64.exe` installer from the repository release.
2. Confirm Windows reports `GDS-G` as the verified publisher. Do not continue if the publisher is unknown or the signature is invalid.
3. Choose a per-user installation directory and start Job Apply Pro.
4. The first start creates an OS-protected encryption key, migrates the local database, and starts the bundled loopback backend. Python and Node are not required.

The packaged browser runtime uses Microsoft Edge. Keep Windows and Edge supported and updated.

## Review and enable notifications

The **Actionable notifications** panel always shows current local action alerts. It covers sign-in verification, CAPTCHA and other user intervention, approaching assessment deadlines, stopped or expired workflows, recruiter/interview/offer messages, due follow-ups, upcoming synced interviews, backup failures, and update failures. Select an in-app alert to move to the relevant workflow, challenge, communication, or operations section. Calendar reminders use generic 24-hour and one-hour wording and never expose the event title, participants, provider identifier, location, or meeting URL.

Native Windows delivery is off by default. Select **Enable** in the notification panel to opt in. The preference and stable delivered-event identifiers are stored in a bounded local state file; message bodies and account details are not stored there. The app checks once per minute, retains at most 50 active alerts, and shows no more than five new native alerts during one refresh. Selecting a Windows notification focuses Job Apply Pro and opens a fixed workbench section.

Notification wording is intentionally generic. Windows can display notifications on a locked screen or retain them in Notification Center, so native text never includes employer or job names, candidate data, message senders or subjects, follow-up reasons, diagnostics, passwords, tokens, or security codes. If Windows notifications are unavailable or disabled, in-app alerts continue to work. Use **Disable** to stop future native delivery. Windows Focus Assist, locked-screen display, click activation, and sleep/resume behavior remain part of the physical release-lab checklist.

## Connect email and calendars

Job Apply Pro does not accept mailbox passwords. Each provider connection uses the system browser, OAuth Authorization Code with PKCE, a one-time loopback callback, and encrypted local token storage.

After a Google Calendar or Outlook Calendar connection reports read access, select **Sync calendar**. The app reads events from one day before the current time through 60 days ahead, stores sensitive event details in the encrypted local database, removes events no longer returned within the refreshed snapshot, and reports only counts and the window end date. Calendar synchronization is manual in this build; there are no background provider webhooks or push subscriptions. The notification check reads the local snapshot once per minute and does not create additional provider traffic.

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
2. Start the visible browser. Sign in directly inside that browser. Do not place a username, password, security code, or token in environment variables, source, documentation, chat, or the application notes.
3. Complete MFA, email codes, CAPTCHA, assessments, terms acceptance, legal attestations, and signatures yourself. Select **Capture current page** after each manual boundary so the app records a fresh fingerprint and classification.
4. Review the current URL, page type, intervention reasons, evidence count, and the complete application in the provider UI.
5. To test automated final submission, separately set `JAP_SUPERVISED_PORTAL_SUBMISSION_ENABLED=true`, restart, return to the same persistent profile, and capture the final review page again. Select **Review & submit exact application** only when the displayed application is correct. The native dialog is the last approval boundary.
6. Treat only an identifier-backed provider confirmation as confirmed. If the result is uncertain, the run records `SUBMISSION_UNCERTAIN`; verify directly in the provider account instead of retrying blindly.
7. Select **Stop & preserve trace** when complete. Remove the portal from the allowlist and disable both supervised gates after the approved window.

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

To restore:

1. Verify the selected backup.
2. Select **Stage restore** and review the displayed fingerprint and file count.
3. Select **Apply staged restore** and read the warning.
4. Confirm only if the fingerprint is still the reviewed value. The app stops its backend, applies the staged files offline, retains the prior database as `job-apply-pro.db.pre-restore`, migrates if required, and restarts.
5. Confirm the dashboard, candidate records, and backup status are expected before continuing work.

If recovery fails, do not repeatedly overwrite files. Export diagnostics and follow the rollback runbook.

## Diagnostics

Select **Export diagnostics** and choose a destination. The JSON package contains build/runtime versions, counts, health states, byte totals, error classifications, safe context key names, and trace file metadata. It does not contain candidate content, error values, credentials, tokens, full paths, screenshots, trace contents, or browser cookies. Review the file before sharing it.

## Updates

Select **Check for updates**. Available updates are downloaded only after **Download update** is selected and installed only after **Restart and install** is selected. The app rejects publisher-signature failures and version downgrades. Back up before updating. If an update is not accepted, keep the current version and export diagnostics.

## Getting help

Include the application version, Windows version, steps to reproduce, and the reviewed diagnostic export. Never send resumes, passwords, provider tokens, database files, browser profiles, or unredacted screenshots through a public issue.
