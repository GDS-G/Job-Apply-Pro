import json
from pathlib import Path

from job_apply_pro import __version__


def test_release_metadata_is_synchronized() -> None:
    root = Path(__file__).parents[2]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    build = json.loads((root / "build.json").read_text(encoding="utf-8"))
    workspace = json.loads((root / "package.json").read_text(encoding="utf-8"))
    desktop = json.loads((root / "apps" / "desktop" / "package.json").read_text(encoding="utf-8"))
    contracts = json.loads(
        (root / "packages" / "contracts" / "package.json").read_text(encoding="utf-8")
    )

    assert version == __version__ == "0.2.0-alpha.1"
    assert build == {
        "name": "Core",
        "version": version,
        "channel": "alpha",
        "roadmap_phases": [0, 1, 2],
        "production_automation_enabled": False,
    }
    assert workspace["version"] == desktop["version"] == contracts["version"] == version
