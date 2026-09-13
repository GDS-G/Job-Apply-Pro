"""Early filesystem-only admission; never imports candidate storage or models."""

import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from sqlalchemy.engine import make_url

from job_apply_pro.config import Settings
from job_apply_pro.storage.restore_gate_repository import (
    RestoreAdmissionError,
    RestoreGateRepository,
    checked_path,
    owns_restore,
    workspace_access,
)


def sqlite_database_path(database_url: str) -> Path | None:
    """SQLAlchemy-compatible parsing without importing storage or opening a DB."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return None
    if url.query or (url.database and url.database.startswith("file:")):
        raise RestoreAdmissionError(
            "SQLite URI/query overrides are not supported by safe restore admission"
        )
    if not url.database or url.database == ":memory:":
        return None
    return Path(url.database).absolute()


def assert_no_sqlite_sidecars(database: Path) -> None:
    """Inspect only paths: opening SQLite could consume recovery sidecars."""
    database = checked_path(database)
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            database.with_name(database.name + suffix).lstat()
        except FileNotFoundError:
            continue
        raise RestoreAdmissionError(
            "Restore requires a cleanly closed SQLite database; preserve existing journal "
            "sidecars and reopen the original workspace safely before retrying"
        )


def closed_restore_database_path(database_url: str) -> Path:
    """Restore-only precondition; normal startup may still recover SQLite journals."""
    database = sqlite_database_path(database_url)
    if database is None:
        raise RestoreAdmissionError("Restore requires an app-owned file-backed SQLite database")
    assert_restore_source_closed(database)
    return database


def assert_restore_source_closed(database: Path) -> None:
    database = checked_path(database)
    try:
        info = database.lstat()
    except OSError:
        raise RestoreAdmissionError(
            "Restore requires the existing original database; preserve the workspace and key"
        ) from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RestoreAdmissionError("Restore requires an existing, exclusively owned database file")
    assert_no_sqlite_sidecars(database)


def workspace_roots(settings: Settings) -> list[Path]:
    roots: set[Path] = set()
    if settings.workspace_root is not None:
        roots.add(checked_path(settings.workspace_root))
    database = sqlite_database_path(settings.database_url)
    if database is not None:
        roots.add(checked_path(database.parent))
    return sorted(roots)


def assert_runtime_admission(settings: Settings) -> None:
    for root in workspace_roots(settings):
        if not owns_restore(root):
            RestoreGateRepository(root).assert_clear()


@contextmanager
def runtime_access(settings: Settings) -> Iterator[None]:
    assert_runtime_admission(settings)
    with ExitStack() as stack:
        for root in workspace_roots(settings):
            stack.enter_context(workspace_access(root))
        yield
