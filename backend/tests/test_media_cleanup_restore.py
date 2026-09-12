import io
import json
import sqlite3
import zipfile
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from job_apply_pro.domain.operations import (
    BackupCategory,
    BackupCreate,
    BackupManifest,
    RestorePlan,
    RestoreStatus,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.backup import BackupError, BackupService
from job_apply_pro.storage.operations_repository import OperationsRepository


def _database(path: Path, states: Sequence[str | None] | None = None) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE local_data (value TEXT)")
        connection.execute("INSERT INTO local_data VALUES ('current-local-data')")
        if states is not None:
            connection.execute("CREATE TABLE ai_media_cleanup (id INTEGER PRIMARY KEY, state TEXT)")
            connection.executemany(
                "INSERT INTO ai_media_cleanup (state) VALUES (?)", [(state,) for state in states]
            )


@dataclass(frozen=True)
class RestoreFiles:
    database: Path
    documents: Path
    staging: Path
    plan: RestorePlan
    staged_database: Path
    document: Path
    staged_document: Path

    def apply(self) -> None:
        BackupService.apply_staged_files(
            self.plan,
            database_url=f"sqlite:///{self.database.as_posix()}",
            document_dir=self.documents,
            staging_dir=self.staging,
        )

    def assert_not_replaced(self, original_database: bytes | None) -> None:
        if original_database is None:
            assert not self.database.exists()
        else:
            assert self.database.read_bytes() == original_database
        assert not self.database.with_suffix(".db.pre-restore").exists()
        assert not self.database.with_suffix(".db.restore.tmp").exists()
        assert self.document.read_bytes() == b"current-encrypted-document"
        assert self.staged_document.read_bytes() == b"staged-encrypted-document"
        assert self.staged_database.read_bytes() == b"verified-staged-database"


@pytest.fixture
def restore_files(tmp_path: Path) -> RestoreFiles:
    database = tmp_path / "current.db"
    documents = tmp_path / "documents"
    staging = tmp_path / "restore-staging"
    staged = staging / "reviewed-plan"
    staged_database = staged / "database" / "job_apply_pro.db"
    staged_document = staged / "documents" / "resume.enc"
    document = documents / "resume.enc"
    documents.mkdir()
    staged_database.parent.mkdir(parents=True)
    staged_document.parent.mkdir()
    document.write_bytes(b"current-encrypted-document")
    staged_database.write_bytes(b"verified-staged-database")
    staged_document.write_bytes(b"staged-encrypted-document")
    return RestoreFiles(
        database=database,
        documents=documents,
        staging=staging,
        plan=RestorePlan(
            id="reviewed-plan",
            backup_id="verified-backup",
            categories={BackupCategory.DATABASE, BackupCategory.DOCUMENTS},
            staged_path=str(staged),
            file_count=2,
            fingerprint="a" * 64,
            status=RestoreStatus.STAGED,
            created_at=datetime(2026, 9, 12, tzinfo=UTC),
        ),
        staged_database=staged_database,
        document=document,
        staged_document=staged_document,
    )


@pytest.mark.parametrize(
    "state",
    [
        "UPLOADING",
        "IN_USE",
        "DELETE_PENDING",
        "MANUAL_REVIEW",
        "UNKNOWN",
        None,
        "",
        "deleted",
        "DELETED ",
    ],
)
def test_restore_blocks_every_non_deleted_current_cleanup_state(
    restore_files: RestoreFiles, state: str | None
) -> None:
    _database(restore_files.database, ["DELETED", state])
    original = restore_files.database.read_bytes()

    with pytest.raises(BackupError, match="unresolved provider media cleanup"):
        restore_files.apply()

    restore_files.assert_not_replaced(original)


@pytest.mark.parametrize("states", [["DELETED", "DELETED"], [], None])
def test_restore_allows_deleted_empty_or_legacy_journal_and_preserves_previous_database(
    restore_files: RestoreFiles, states: list[str | None] | None
) -> None:
    _database(restore_files.database, states)
    original = restore_files.database.read_bytes()

    restore_files.apply()

    assert restore_files.database.read_bytes() == b"verified-staged-database"
    assert restore_files.database.with_suffix(".db.pre-restore").read_bytes() == original
    assert restore_files.document.read_bytes() == b"staged-encrypted-document"
    assert restore_files.staged_database.read_bytes() == b"verified-staged-database"
    assert restore_files.staged_document.read_bytes() == b"staged-encrypted-document"


@pytest.mark.parametrize("current_content", [b"not-a-sqlite-database", None])
def test_restore_blocks_corrupt_or_missing_current_database_without_touching_files(
    restore_files: RestoreFiles, current_content: bytes | None
) -> None:
    if current_content is not None:
        restore_files.database.write_bytes(current_content)

    with pytest.raises(BackupError, match="cannot be inspected"):
        restore_files.apply()

    restore_files.assert_not_replaced(current_content)


def test_restore_inspection_opens_read_only_and_fails_closed_on_sqlite_error(
    restore_files: RestoreFiles,
) -> None:
    _database(restore_files.database, ["DELETED"])
    original = restore_files.database.read_bytes()
    with (
        patch(
            "job_apply_pro.services.backup.sqlite3.connect",
            side_effect=sqlite3.OperationalError("access denied"),
        ) as connect,
        pytest.raises(BackupError, match="cannot be inspected"),
    ):
        restore_files.apply()

    connect.assert_called_once()
    args, kwargs = connect.call_args
    assert args[0] == f"{restore_files.database.resolve().as_uri()}?mode=ro"
    assert kwargs["uri"] is True
    restore_files.assert_not_replaced(original)


def test_restore_inspection_reads_committed_cleanup_state_from_wal(
    restore_files: RestoreFiles,
) -> None:
    _database(restore_files.database, [])
    # Keep the WAL open without further writes during the restore attempt.
    # An immutable connection would miss this committed cleanup obligation.
    with closing(sqlite3.connect(restore_files.database)) as keeper:
        assert keeper.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        keeper.execute("PRAGMA wal_autocheckpoint=0")
        keeper.execute("INSERT INTO ai_media_cleanup (state) VALUES ('MANUAL_REVIEW')")
        keeper.commit()
        original = restore_files.database.read_bytes()
        wal = restore_files.database.with_name(restore_files.database.name + "-wal")
        original_wal = wal.read_bytes()
        assert b"MANUAL_REVIEW" not in original
        assert b"MANUAL_REVIEW" in original_wal

        with pytest.raises(BackupError, match="unresolved provider media cleanup"):
            restore_files.apply()

        restore_files.assert_not_replaced(original)
        assert wal.read_bytes() == original_wal


@pytest.mark.parametrize(
    "journal_schema",
    [
        "CREATE VIEW ai_media_cleanup AS SELECT 'DELETED' AS state",
        "CREATE TABLE ai_media_cleanup (unexpected_column TEXT)",
    ],
)
def test_restore_blocks_uninspectable_journal_schema(
    restore_files: RestoreFiles, journal_schema: str
) -> None:
    _database(restore_files.database)
    with closing(sqlite3.connect(restore_files.database)) as connection, connection:
        connection.execute(journal_schema)
    original = restore_files.database.read_bytes()

    with pytest.raises(BackupError, match="cannot be inspected"):
        restore_files.apply()

    restore_files.assert_not_replaced(original)


@pytest.mark.parametrize("database_exists", [True, False])
def test_document_only_restore_does_not_inspect_database(
    restore_files: RestoreFiles, database_exists: bool
) -> None:
    if database_exists:
        _database(restore_files.database, ["MANUAL_REVIEW"])
    original = restore_files.database.read_bytes() if database_exists else None
    document_plan = restore_files.plan.model_copy(update={"categories": {BackupCategory.DOCUMENTS}})
    with patch("job_apply_pro.services.backup.sqlite3.connect") as connect:
        BackupService.apply_staged_files(
            document_plan,
            database_url=f"sqlite:///{restore_files.database.as_posix()}",
            document_dir=restore_files.documents,
            staging_dir=restore_files.staging,
        )

    connect.assert_not_called()
    assert restore_files.document.read_bytes() == b"staged-encrypted-document"
    assert restore_files.staged_document.read_bytes() == b"staged-encrypted-document"
    if original is None:
        assert not restore_files.database.exists()
    else:
        assert restore_files.database.read_bytes() == original
    assert not restore_files.database.with_suffix(".db.pre-restore").exists()


def test_backup_schema_revision_matches_the_single_alembic_head() -> None:
    configuration = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    assert ScriptDirectory.from_config(configuration).get_heads() == [BackupService.SCHEMA_REVISION]


def test_encrypted_database_backup_includes_cleanup_journal_rows(tmp_path: Path) -> None:
    database = tmp_path / "current.db"
    states = ["UPLOADING", "DELETE_PENDING", "MANUAL_REVIEW", "DELETED"]
    _database(database, states)
    original = database.read_bytes()
    manifests: dict[str, BackupManifest] = {}

    def save_backup(manifest: BackupManifest) -> BackupManifest:
        manifests[manifest.id] = manifest
        return manifest

    repository = Mock(spec=OperationsRepository)
    repository.save_backup.side_effect = save_backup
    repository.get_backup.side_effect = manifests.get
    cipher = SensitiveDataCipher(StaticKeyProvider(b"m" * 32))
    service = BackupService(
        cast(OperationsRepository, repository),
        cipher,
        database_url=f"sqlite:///{database.as_posix()}",
        document_dir=tmp_path / "documents",
        backup_dir=tmp_path / "backups",
        staging_dir=tmp_path / "restore-staging",
    )

    manifest = service.create(BackupCreate(categories={BackupCategory.DATABASE}))

    encrypted = Path(manifest.archive_path).read_text(encoding="ascii")
    assert encrypted.startswith("jap:v1:")
    assert "MANUAL_REVIEW" not in encrypted
    archive = cipher.decrypt_bytes(encrypted, context=f"backup:{manifest.id}:archive")
    snapshot = tmp_path / "snapshot.db"
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        snapshot.write_bytes(bundle.read("database/job_apply_pro.db"))
        metadata = json.loads(bundle.read("manifest.json"))
    with closing(sqlite3.connect(snapshot)) as connection:
        rows = connection.execute("SELECT state FROM ai_media_cleanup ORDER BY id").fetchall()
    assert rows == [(state,) for state in states]
    assert metadata["schema_revision"] == BackupService.SCHEMA_REVISION
    assert manifest.schema_revision == BackupService.SCHEMA_REVISION
    assert service.verify(manifest.id).valid
    assert database.read_bytes() == original
