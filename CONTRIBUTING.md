# Contributing

## Branches and releases

Milestone branches use `codex/<build-name>-v<semver>` for Codex-led work. Human feature branches may use `feature/<description>` and repairs may use `fix/<description>`.

Versions follow SemVer:

- `0.x` is pre-production development.
- `alpha.N` may change contracts and is intended for development validation.
- `beta.N` is feature-complete for its milestone and focuses on compatibility and defects.
- release candidates use `rc.N`; stable releases use `MAJOR.MINOR.PATCH`.

Build names describe milestone scope and are not part of compatibility rules. Tags use `v<semver>`.

## Pull requests

Pull requests must describe scope, affected requirements, tests, security impact, migrations, screenshots or traces when applicable, and rollback considerations. Keep generated output and local data out of commits.

## Definition of done

A change is complete when code, tests, migrations, contracts, documentation, and operational guidance agree and the relevant validation commands pass.
