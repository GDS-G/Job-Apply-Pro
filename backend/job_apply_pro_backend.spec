from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

repo_root = Path.cwd()
playwright_datas, playwright_binaries, playwright_hidden = collect_all("playwright")

analysis = Analysis(
    [str(repo_root / "backend" / "src" / "job_apply_pro" / "desktop_entry.py")],
    pathex=[str(repo_root / "backend" / "src")],
    binaries=playwright_binaries,
    datas=[
        (str(repo_root / "backend" / "alembic.ini"), "."),
        (str(repo_root / "backend" / "migrations"), "migrations"),
        *playwright_datas,
    ],
    hiddenimports=[
        *playwright_hidden,
        *collect_submodules("sqlalchemy.dialects.sqlite"),
        *collect_submodules("uvicorn"),
    ],
    excludes=["pytest", "mypy", "ruff", "reportlab"],
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
