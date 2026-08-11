# ADR-0002: Build naming and semantic versioning

- Status: Accepted
- Build: Foundation `v0.1.0-alpha.1`

## Context

The legacy repository had no usable application version policy. Builds need human-readable milestone identity without making codenames part of compatibility decisions.

## Decision

Use Semantic Versioning for every application and contract version. Use a short descriptive build name for each milestone. Pre-1.0 builds use prerelease identifiers such as `alpha.1`, `beta.1`, and `rc.1`.

Canonical forms:

- Display: `Foundation v0.1.0-alpha.1`
- Branch: `codex/foundation-v0.1.0-alpha.1`
- Tag: `v0.1.0-alpha.1`
- Release branch when needed: `release/0.1`

All root, desktop, backend, contract, API, and build metadata versions advance together until independent package versioning becomes necessary.

## Consequences

Automation can compare SemVer values while users and developers can discuss a memorable milestone name. Build names can change without changing compatibility guarantees.
