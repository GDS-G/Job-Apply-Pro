# Job Apply Pro user guide

This guide applies to Calendar Interview Awareness `v0.21.0-alpha.1`. This is an alpha build: named portal capability is disabled by default and is not a production compatibility claim. Native Windows notifications are source-complete but still require physical release-lab validation. Live mail/calendar access remains unavailable until the owner registers an OAuth desktop client, imports reviewed registration metadata, and completes provider authorization.

## Install and start

1. Download the signed `Job-Apply-Pro-0.21.0-alpha.1-x64.exe` installer from the repository release.
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

Current limitations: LibreOffice and Tesseract are not bundled; OCR language data must be installed locally; complex multi-column reading order remains conservative; deterministic token matching is conservative; and advanced visual templates are not yet implemented.

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
