"""Restore refuses journal recovery before even reading its selected plan."""

import hashlib
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from job_apply_pro.domain.operations import RestoreConfirmation
from job_apply_pro.restore_admission import closed_restore_database_path, runtime_access
from job_apply_pro.services.backup import BackupService
from job_apply_pro.storage.operations_repository import OperationsRepository
from job_apply_pro.storage.restore_gate_repository import RestoreAdmissionError, workspace_access
from test_restore_admission import PROJECT, Workspace, environment, run
from test_restore_admission import workspace as workspace


def _hot_journal(value: Workspace) -> bytes:
    # Force dirty-page spilling, then terminate only this synthetic writer.
    # No production crash switch or environment-controlled bypass is added.
    with closing(sqlite3.connect(value.database)) as connection, connection:
        connection.execute("CREATE TABLE sidecar_probe (id INTEGER PRIMARY KEY, payload BLOB)")
        connection.executemany(
            "INSERT INTO sidecar_probe(payload) VALUES (?)", [(b"a" * 2048,)] * 100
        )
    result = run(
        value.root,
        "-c",
        "import os,sqlite3\n"
        "database = os.environ['JAP_DATABASE_URL'].removeprefix('sqlite:///')\n"
        "connection = sqlite3.connect(database)\n"
        "connection.execute('PRAGMA cache_size=5')\n"
        "connection.execute('BEGIN IMMEDIATE')\n"
        "connection.execute('UPDATE sidecar_probe SET payload=?', (b'b'*2048,))\n"
        "os._exit(79)\n",
    )
    assert result.returncode == 79, result.stderr
    journal = value.database.with_name("app.db-journal").read_bytes()
    assert len(journal) > 512
    assert journal[:8] == bytes.fromhex("d9d505f920a163d7")
    return journal


@pytest.mark.parametrize("driver", ["sqlite", "sqlite+pysqlite"])
@pytest.mark.parametrize("has_key", [False, True])
def test_restore_cli_preserves_hot_journal_before_invalid_plan_lookup(
    workspace: Workspace, driver: str, has_key: bool
) -> None:
    journal = _hot_journal(workspace)
    before = hashlib.sha256(workspace.database.read_bytes()).hexdigest()
    configured = environment(workspace.root)
    configured["JAP_DATABASE_URL"] = f"{driver}:///{workspace.database.as_posix()}"
    if not has_key:
        configured.pop("JAP_MASTER_KEY")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "job_apply_pro.desktop_entry",
            "restore",
            "--plan-id",
            "missing-plan",
            "--fingerprint",
            "a" * 64,
        ],
        env=configured,
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 3
    assert "Offline restore admission failed" in result.stderr
    assert "Traceback" not in result.stderr
    assert "missing-plan" not in result.stderr
    assert hashlib.sha256(workspace.database.read_bytes()).hexdigest() == before
    assert workspace.database.with_name("app.db-journal").read_bytes() == journal
    assert not workspace.gate.blocked()
    assert not (workspace.gate.control / "operations").exists()


def test_owned_restore_checks_sidecars_before_importing_database(workspace: Workspace) -> None:
    journal = _hot_journal(workspace)
    before = workspace.database.read_bytes()
    result = run(
        workspace.root,
        "-c",
        "import os,sys\n"
        "from pathlib import Path\n"
        "from job_apply_pro.desktop_entry import _restore_owned\n"
        "from job_apply_pro.storage.restore_gate_repository import RestoreAdmissionError\n"
        "assert 'job_apply_pro.storage.database' not in sys.modules\n"
        "try:\n"
        " _restore_owned('missing-plan', 'a'*64, Path(os.environ['JAP_WORKSPACE_ROOT']))\n"
        "except RestoreAdmissionError:\n"
        " assert 'job_apply_pro.storage.database' not in sys.modules\n"
        "else:\n"
        " raise AssertionError('Restore admitted an existing journal')\n",
    )
    assert result.returncode == 0, result.stderr
    assert workspace.database.read_bytes() == before
    assert workspace.database.with_name("app.db-journal").read_bytes() == journal
    assert not workspace.gate.blocked()


@pytest.mark.parametrize("direct_owned", [False, True])
def test_direct_document_restore_rejects_before_repository_read(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, direct_owned: bool
) -> None:
    journal = _hot_journal(workspace)
    before = workspace.database.read_bytes()
    url = f"sqlite:///{workspace.database.as_posix()}"
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            repository = OperationsRepository(session)

            def no_read(_plan_id: str) -> None:
                pytest.fail("Restore must inspect sidecars before repository access")

            monkeypatch.setattr(repository, "get_restore_plan", no_read)
            service = BackupService(
                repository,
                workspace.cipher,
                database_url=url,
                document_dir=workspace.root / "documents",
                backup_dir=workspace.root / "backups",
                staging_dir=workspace.root / "restore-staging",
            )
            confirmation = RestoreConfirmation(
                fingerprint=workspace.plan.fingerprint,
                confirmation_phrase=BackupService.RESTORE_PHRASE,
            )
            with (
                workspace_access(workspace.root, restore=True),
                pytest.raises(RestoreAdmissionError, match="sidecars"),
            ):
                if direct_owned:
                    service._apply_documents_owned(workspace.plan.id, confirmation)
                else:
                    service.apply_offline(workspace.plan.id, confirmation)
    finally:
        engine.dispose()
    assert workspace.database.read_bytes() == before
    assert workspace.database.with_name("app.db-journal").read_bytes() == journal
    assert not workspace.gate.blocked()


def test_normal_runtime_admission_does_not_disable_sqlite_recovery(workspace: Workspace) -> None:
    from job_apply_pro.config import Settings

    _hot_journal(workspace)
    settings = Settings(
        workspace_root=workspace.root,
        database_url=f"sqlite:///{workspace.database.as_posix()}",
    )
    with runtime_access(settings), closing(sqlite3.connect(workspace.database)) as connection:
        recovered = connection.execute("SELECT payload FROM sidecar_probe LIMIT 1").fetchone()
        assert recovered is not None and recovered[0] == b"a" * 2048
    assert not workspace.database.with_name("app.db-journal").exists()


@pytest.mark.parametrize("driver", ["sqlite", "sqlite+pysqlite"])
@pytest.mark.parametrize("explicit_workspace", [False, True])
def test_missing_database_restore_never_creates_database_guard_or_key(
    tmp_path: Path, driver: str, explicit_workspace: bool
) -> None:
    configured = environment(tmp_path)
    configured["JAP_DATABASE_URL"] = f"{driver}:///{(tmp_path / 'app.db').as_posix()}"
    configured.pop("JAP_MASTER_KEY")
    if not explicit_workspace:
        configured.pop("JAP_WORKSPACE_ROOT")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "job_apply_pro.desktop_entry",
            "restore",
            "--plan-id",
            "missing-plan",
            "--fingerprint",
            "a" * 64,
        ],
        env=configured,
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 3
    assert "Offline restore admission failed" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "app.db").exists()
    assert not (tmp_path / "restore-control" / "active.guard").exists()
    assert not (tmp_path / "restore-control" / "operations").exists()
    assert not (tmp_path / "master-key.bin").exists()
    assert not (tmp_path / "documents").exists()


@pytest.mark.parametrize("kind", ["missing", "directory", "hardlink"])
def test_restore_database_preflight_requires_existing_exclusively_owned_file(
    tmp_path: Path, kind: str
) -> None:
    database = tmp_path / "app.db"
    if kind == "directory":
        database.mkdir()
    elif kind == "hardlink":
        original = tmp_path / "original.db"
        original.write_bytes(b"original database bytes")
        database.hardlink_to(original)
    with pytest.raises(RestoreAdmissionError):
        closed_restore_database_path(f"sqlite:///{database.as_posix()}")


@pytest.mark.parametrize("linked_component", ["final", "parent"])
def test_restore_database_preflight_rejects_linked_paths_before_open(
    tmp_path: Path, linked_component: str
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    content = b"original database bytes"
    (original / "app.db").write_bytes(content)
    link = tmp_path / "redirected"
    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(original)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(original, target_is_directory=True)
    database = link if linked_component == "final" else link / "app.db"
    with pytest.raises(RestoreAdmissionError, match=r"linked|redirected"):
        closed_restore_database_path(f"sqlite:///{database.as_posix()}")
    assert (original / "app.db").read_bytes() == content
