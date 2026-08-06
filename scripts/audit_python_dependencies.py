"""Run pip-audit with narrowly scoped, expiring advisory exceptions."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXCEPTIONS_PATH = ROOT / "security" / "python-audit-exceptions.json"


def _load_exceptions() -> dict[tuple[str, str], dict[str, Any]]:
    payload = json.loads(EXCEPTIONS_PATH.read_text(encoding="utf-8"))
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in payload.get("exceptions", []):
        key = (entry["package"], entry["advisory_id"])
        if key in entries:
            raise ValueError(f"Duplicate dependency-audit exception: {key}")
        entries[key] = entry
    return entries


def _usage_guard_passes(entry: dict[str, Any]) -> tuple[bool, str]:
    forbidden = entry.get("forbidden_substrings", [])
    for relative_path in entry.get("scan_paths", []):
        scan_root = ROOT / relative_path
        for source in scan_root.rglob("*.py"):
            content = source.read_text(encoding="utf-8")
            for substring in forbidden:
                if substring in content:
                    return False, f"{substring!r} found in {source.relative_to(ROOT)}"
    return True, ""


def main() -> int:
    audit = subprocess.run(
        [sys.executable, "-m", "pip_audit", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(audit.stdout)
        exceptions = _load_exceptions()
    except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"Dependency audit configuration/error: {error}", file=sys.stderr)
        if audit.stderr:
            print(audit.stderr.strip(), file=sys.stderr)
        return 2

    unexpected: list[str] = []
    accepted: list[str] = []
    today = datetime.now(tz=UTC).date()

    for dependency in report.get("dependencies", []):
        package = dependency.get("name", "")
        version = dependency.get("version", "")
        for vulnerability in dependency.get("vulns", []):
            advisory_id = vulnerability.get("id", "")
            entry = exceptions.get((package, advisory_id))
            label = f"{package} {version}: {advisory_id}"
            if entry is None:
                unexpected.append(f"{label} (no approved exception)")
                continue
            expires_on = date.fromisoformat(entry["expires_on"])
            if today > expires_on:
                unexpected.append(f"{label} (exception expired {expires_on.isoformat()})")
                continue
            if version not in entry.get("allowed_versions", []):
                unexpected.append(f"{label} (version is outside the approved exception)")
                continue
            guard_passed, guard_error = _usage_guard_passes(entry)
            if not guard_passed:
                unexpected.append(f"{label} (usage guard failed: {guard_error})")
                continue
            accepted.append(
                f"{label} accepted through {expires_on.isoformat()} -- {entry['reason']}"
            )

    for line in accepted:
        print(f"TEMPORARY EXCEPTION: {line}")
    if unexpected:
        for line in unexpected:
            print(f"AUDIT FAILURE: {line}", file=sys.stderr)
        return 1
    if audit.returncode not in (0, 1):
        print(audit.stderr.strip(), file=sys.stderr)
        return audit.returncode
    print(f"Python dependency audit passed ({len(accepted)} temporary exception(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
