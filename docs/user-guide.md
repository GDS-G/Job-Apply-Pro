# Job Apply Pro user guide

This guide applies to Provider Connectivity `v0.13.0-alpha.1`. This is an alpha build: real portal submission remains disabled, and live mail/calendar access remains unavailable until the owner registers an OAuth desktop client, reviews scopes, and completes provider authorization.

## Install and start

1. Download the signed `Job-Apply-Pro-0.13.0-alpha.1-x64.exe` installer from the repository release.
2. Confirm Windows reports `GDS-G` as the verified publisher. Do not continue if the publisher is unknown or the signature is invalid.
3. Choose a per-user installation directory and start Job Apply Pro.
4. The first start creates an OS-protected encryption key, migrates the local database, and starts the bundled loopback backend. Python and Node are not required.

The packaged browser runtime uses Microsoft Edge. Keep Windows and Edge supported and updated.

## Connect email and calendars

Job Apply Pro does not accept mailbox passwords. Each provider connection uses the system browser, OAuth Authorization Code with PKCE, a one-time loopback callback, and encrypted local token storage.

Before **Review & connect** becomes available, the owner must register a public desktop application with the provider and place its public client ID plus reviewed scopes in local `JAP_COMMUNICATION_CONFIG_JSON`. Do not put client registrations, tokens, or passwords in Git, GitHub Actions, the Google development document, or chat.

For Google:

1. Create or select a Google Cloud project, enable the Gmail and/or Calendar APIs, configure the OAuth consent screen, and create an OAuth client of type **Desktop app**.
2. Register the loopback redirect `http://127.0.0.1:8765/api/v1/communications/oauth/callback`.
3. Request only the capabilities in use. This build allowlists `gmail.readonly`, `gmail.send`, `calendar.readonly`, and `calendar.events`, plus `openid` and `email`.
4. Review Google's [desktop OAuth flow](https://developers.google.com/identity/protocols/oauth2/native-app), [Gmail scope classifications](https://developers.google.com/workspace/gmail/api/auth/scopes), and [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth). Gmail read access is currently a restricted scope and public distribution may require Google verification and an independent security assessment.

For Microsoft:

1. Create an app registration in Microsoft Entra, configure it as a public desktop client, and add the same loopback redirect URI.
2. Add only delegated Microsoft Graph permissions in use: `User.Read`, `Mail.Read`, `Mail.Send`, and/or `Calendars.ReadWrite`, with `openid`, `email`, and `offline_access` for sign-in and refresh.
3. Review Microsoft's [authorization-code/PKCE flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow), [desktop app registration guidance](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration), and [Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference). An organization may require administrator consent.

After configuration, select **Review & connect**, verify the provider host and displayed scopes, sign in manually, complete any MFA, and approve only the expected access. Return to Job Apply Pro and refresh the dashboard. Use **Revoke access** to revoke at the provider where supported and always delete the encrypted local credential. Microsoft may also require revocation from the account's application-consent page.

## Safety model

- The desktop keeps profile and workflow data locally and encrypts sensitive values.
- Portal automation is untrusted input. A prepared application is not a confirmed submission.
- CAPTCHA, legal attestation, signature, and uncertain confirmation states require direct review.
- Catalog entries marked replay-tested are not production-enabled integrations.

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
