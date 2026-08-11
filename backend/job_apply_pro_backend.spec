from importlib.metadata import distribution
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

repo_root = Path.cwd()
playwright_datas, playwright_binaries, playwright_hidden = collect_all("playwright")
reportlab_datas, reportlab_binaries, reportlab_hidden = collect_all("reportlab")
pdfium_datas, pdfium_binaries, pdfium_hidden = collect_all("pypdfium2")
pdfium_distribution = distribution("pypdfium2")
pdfium_license_datas = []
for distribution_file in pdfium_distribution.files or []:
    normalized = str(distribution_file).replace("\\", "/")
    marker = ".dist-info/licenses/"
    if marker in normalized:
        relative_license = Path(normalized.split(marker, 1)[1])
        destination = Path("third-party-licenses/pypdfium2") / relative_license.parent
        pdfium_license_datas.append(
            (str(pdfium_distribution.locate_file(distribution_file)), str(destination))
        )

analysis = Analysis(
    [str(repo_root / "backend" / "src" / "job_apply_pro" / "desktop_entry.py")],
    pathex=[str(repo_root / "backend" / "src")],
    binaries=[*playwright_binaries, *reportlab_binaries, *pdfium_binaries],
    datas=[
        (str(repo_root / "backend" / "alembic.ini"), "."),
        (str(repo_root / "backend" / "migrations"), "migrations"),
        *playwright_datas,
        *reportlab_datas,
        *pdfium_datas,
        *pdfium_license_datas,
    ],
    hiddenimports=[
        *playwright_hidden,
        *reportlab_hidden,
        *pdfium_hidden,
        *collect_submodules("sqlalchemy.dialects.sqlite"),
        *collect_submodules("uvicorn"),
    ],
    excludes=["pytest", "mypy", "ruff"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="job-apply-pro-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="job-apply-pro-backend",
)
