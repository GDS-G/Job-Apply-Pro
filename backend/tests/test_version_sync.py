import json
import re
import tomllib
from pathlib import Path

from job_apply_pro import __version__
from job_apply_pro.services.support import SupportService


def test_release_metadata_is_synchronized() -> None:
    root = Path(__file__).parents[2]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    build = json.loads((root / "build.json").read_text(encoding="utf-8"))
    workspace = json.loads((root / "package.json").read_text(encoding="utf-8"))
    desktop = json.loads((root / "apps" / "desktop" / "package.json").read_text(encoding="utf-8"))
    contracts = json.loads(
        (root / "packages" / "contracts" / "package.json").read_text(encoding="utf-8")
    )
    backend = tomllib.loads((root / "backend" / "pyproject.toml").read_text(encoding="utf-8"))

    assert version == __version__ == "0.53.0-alpha.1"
    assert build == {
        "name": "Packaged Browser Runtime",
        "version": version,
        "channel": "alpha",
        "roadmap_phases": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "production_automation_enabled": False,
    }
    assert workspace["version"] == desktop["version"] == contracts["version"] == version
    assert backend["project"]["version"] == "0.53.0a1"
    assert build["name"] == SupportService.BUILD_NAME
    contract_source = (root / "packages/contracts/src/index.ts").read_text(encoding="utf-8")
    build_info_block = contract_source.split("export const buildInfo = {", 1)[1].split(
        "} as const;", 1
    )[0]
    exported_build = dict(re.findall(r'^\s+(\w+): "([^"\n]+)",?$', build_info_block, re.MULTILINE))
    assert exported_build == {key: build[key] for key in ("name", "version", "channel")}
