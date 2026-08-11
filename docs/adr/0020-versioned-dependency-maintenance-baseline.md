# ADR-0020: Versioned dependency maintenance baseline

- Status: Accepted
- Build: Maintenance Refresh `v0.12.1-alpha.1`

## Context

The production-hardening stack was integrated through twelve reviewed milestone branches. Dependabot then opened independent updates for GitHub Actions, JavaScript packages, and Python constraints. Merging those directly would create an unversioned source state, duplicate full Windows validation runs, and allow Node type declarations to drift beyond the supported Node 24 runtime.

## Decision

Consolidate compatible dependency updates into a named application prerelease and advance every application, contract, API, package, UI, and build metadata version together. Keep explicit `@types/node` and Vite peers on the Node 24/Vite 7 baseline in every workspace so Vitest cannot auto-install a second unsupported graph. Keep Vite and its React plugin on the newest major supported by `electron-vite`; Vite 8 remains excluded while the current host tool declares support only through Vite 7. Use Starlette's `httpx2` test-client dependency alongside production `httpx` so the maintained FastAPI test path is exercised without a deprecated fallback. Validate new major versions of development and document-generation dependencies through the complete format, lint, strict-type, test, coverage, build, frozen-backend, package-smoke, dependency-audit, secret-scan, and CodeQL gates.

Group future minor and patch Dependabot updates by ecosystem and cap simultaneous pull requests. Major updates remain independently visible except GitHub Actions, which are grouped because the workflow suite validates them as a single delivery surface.

## Consequences

The audited candidate remains reproducible and dependency refreshes have explicit SemVer identity. Tooling cannot silently compile against a newer Node API surface than the packaged application supports. Vulnerable dependency releases are excluded by raising minimum versions instead of relying on whatever version happens to be installed locally. Maintenance updates still require the same protected-branch evidence as feature releases and do not enable production portal or provider automation.
