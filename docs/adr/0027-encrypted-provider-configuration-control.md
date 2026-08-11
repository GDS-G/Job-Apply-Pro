# ADR-0027: Encrypt and constrain provider configuration control

- Status: Accepted
- Date: 2026-08-11
- Build: Provider Configuration Control `v0.18.0-alpha.1`

## Context

Provider OAuth adapters previously depended entirely on `JAP_COMMUNICATION_CONFIG_JSON`. That fail-closed deployment boundary was secure but left the managed desktop without a usable registration workflow. Copying JSON through the renderer or accepting account passwords, provider tokens, or confidential-client secrets would widen the trust boundary and create new disclosure paths. Replacing an administrator-managed environment value from the UI would also violate deployment ownership.

## Decision

The authenticated loopback API exposes configuration status, validation, import, and clear operations. Import input is a secret-valued string limited to 64 KiB, parsed by the existing strict Pydantic models, and required to contain at least one provider or public OAuth client. Unknown fields are forbidden, so passwords, access tokens, refresh tokens, client secrets, arbitrary endpoints, and extra policy data are rejected. Redirect URIs retain the exact loopback callback constraint, scopes retain existing normalization and allowlisting at OAuth start, and API responses contain only provider, scopes, capability flags, categories, source, and update time.

Accepted desktop configuration is stored as one AES-256-GCM authenticated envelope in the local database using the application master key. The raw JSON and public client IDs remain in Electron main and the authenticated backend; neither crosses the preload boundary. Electron main performs a bounded read of at most 64 KiB plus one sentinel byte, requests a JSON file through the native picker, asks for native confirmation using only the sanitized provider/scope/capability/automatic-category preview, and returns only the sanitized status to the renderer.

`JAP_COMMUNICATION_CONFIG_JSON` is the managed-deployment authority. When it exists, it takes precedence over the encrypted database row and import/clear mutations return a conflict. Clearing requires native confirmation, disables the local registration, and deliberately does not claim to revoke provider consent or delete retained encrypted OAuth tokens; users revoke connections separately before removing access.

## Consequences

The packaged desktop can configure public OAuth registrations without editing process variables or exposing configuration contents to renderer code. Database compromise does not reveal the configuration without the local master key. Tests verify API authentication, sanitized previews, ciphertext storage, environment precedence, rejected secret fields, migration repeatability, and the renderer interaction. Live provider registration, provider review/consent, terms approval, quotas, MFA, security codes, and authorized evidence remain external gates.
