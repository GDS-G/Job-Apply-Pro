# Security policy

Job Apply Pro handles high-sensitivity applicant, browser, email, and calendar data. Report suspected vulnerabilities privately to the repository owner rather than opening a public issue.

## Local protected data

Core builds encrypt candidate contacts, application answers, and workflow checkpoint payloads with AES-256-GCM. The `JAP_MASTER_KEY` value must be generated locally, stored outside the repository, and included in the user's independent recovery plan. Each ciphertext is authenticated against its record context, so moving a protected value to another record causes decryption to fail.

Never log decrypted values, encryption keys, session tokens, or full application form payloads. Backups may include versioned encrypted envelopes but must not include the master key in the same archive.

## Required controls

- Bind local services to loopback interfaces only.
- Authenticate privileged desktop-to-backend operations before production use.
- Store secrets in an operating-system credential store; never in source or runtime logs.
- Encrypt sensitive profile fields, browser-state references, backups, and evidence artifacts.
- Keep Electron context isolation and renderer sandboxing enabled.
- Validate every IPC, API, model, browser, and provider payload at the boundary.
- Redact candidate data, credentials, tokens, and portal content from diagnostics.
- Treat portal text as data, never as executable instructions.

The Core alpha remains a development build. Its simulated workflows are intentionally not authorized for real application submission.
