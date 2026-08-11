# Job Apply Pro user guide

This guide applies to Production Hardening `v0.12.0-alpha.1`. This is an alpha build: real portal submission and live mail/calendar writes remain disabled by default.

## Install and start

1. Download the signed `Job-Apply-Pro-0.12.0-alpha.1-x64.exe` installer from the repository release.
2. Confirm Windows reports `GDS-G` as the verified publisher. Do not continue if the publisher is unknown or the signature is invalid.
3. Choose a per-user installation directory and start Job Apply Pro.
4. The first start creates an OS-protected encryption key, migrates the local database, and starts the bundled loopback backend. Python and Node are not required.

The packaged browser runtime uses Microsoft Edge. Keep Windows and Edge supported and updated.

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
