import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from job_apply_pro.domain.communications import IntegrationProvider, MutationStatus
from job_apply_pro.domain.mail import ProviderMailResult
from job_apply_pro.domain.operations import (
    BackupCategory,
    BackupCreate,
    RestoreCreate,
    RestorePlan,
    RestoreStatus,
)
from job_apply_pro.integrations.communications import ProviderSendUncertainError
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.backup import BackupError, BackupService
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.operations_repository import OperationsRepository
from test_mail_attachment_boundary import _command, _confirmation, _service

_AUDIT_COLUMNS = (
    "id",
    "kind",
    "provider",
    "resource_id",
    "idempotency_key",
    "fingerprint",
    "status",
    "confirmed_by",
    "provider_resource_id",
    "error_code",
    "occurred_at",
)


def _database(path: Path, *, legacy: bool = False) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE local_data (value TEXT)")
        connection.execute("INSERT INTO local_data VALUES ('synthetic-current-data')")
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.execute(
            "INSERT INTO alembic_version VALUES (?)",
            ("20260814_0023" if legacy else "20260913_0024",),
        )
        connection.execute(
            "CREATE TABLE communication_mutation_audits ("
            + ", ".join(f"{name} TEXT" for name in _AUDIT_COLUMNS)
            + ")"
        )
        if not legacy:
            connection.execute("CREATE TABLE mail_send_claims (draft_id TEXT, audit_id TEXT)")


def _attempt(
    connection: sqlite3.Connection, status: str, *, suffix: str = "1", claim: bool = True
) -> None:
    connection.execute(
        "INSERT INTO communication_mutation_audits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            f"audit-{suffix}",
            "SEND_MESSAGE",
            "GMAIL",
            f"draft-{suffix}",
            f"key-{suffix}",
            "a" * 64,
            status,
            "synthetic-reviewer",
            "synthetic-provider-id",
            None,
            "2026-09-13 12:00:00.000000",
        ),
    )
    if claim:
        connection.execute(
            "INSERT INTO mail_send_claims VALUES (?, ?)", (f"draft-{suffix}", f"audit-{suffix}")
        )


def _record(path: Path, status: str = "ACCEPTED", *, suffix: str = "1", claim: bool = True) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        _attempt(connection, status, suffix=suffix, claim=claim)


@dataclass(frozen=True)
class _Restore:
    current: Path
    staged: Path
    document: Path
    staged_document: Path
    plan: RestorePlan

    def apply(self) -> None:
        BackupService.apply_staged_files(
            self.plan,
            database_url=f"sqlite:///{self.current.as_posix()}",
            document_dir=self.document.parent,
            staging_dir=Path(self.plan.staged_path).parent,
        )

    def assert_refused(
        self, *, message: str = "Mail send history|recorded mail send attempts"
    ) -> None:
        original = self.current.read_bytes()
        staged = self.staged.read_bytes() if self.staged.exists() else None
        with pytest.raises(BackupError, match=message) as error:
            self.apply()
        assert "synthetic-provider-id" not in str(error.value)
        assert "draft-1" not in str(error.value)
        assert "key-1" not in str(error.value)
        assert self.current.read_bytes() == original
        assert (self.staged.read_bytes() if self.staged.exists() else None) == staged
        assert not self.current.with_suffix(".db.pre-restore").exists()
        assert not self.current.with_suffix(".db.restore.tmp").exists()
        assert self.document.read_bytes() == b"current encrypted document"
        assert self.staged_document.read_bytes() == b"staged encrypted document"


@pytest.fixture
def restore(tmp_path: Path) -> _Restore:
    current = tmp_path / "current.db"
    staged_root = tmp_path / "staging" / "reviewed-plan"
    staged = staged_root / "database" / "job_apply_pro.db"
    document = tmp_path / "documents" / "resume.enc"
    staged_document = staged_root / "documents" / "resume.enc"
    staged.parent.mkdir(parents=True)
    document.parent.mkdir()
    staged_document.parent.mkdir()
    document.write_bytes(b"current encrypted document")
    staged_document.write_bytes(b"staged encrypted document")
    _database(current)
    shutil.copyfile(current, staged)
    return _Restore(
        current,
        staged,
        document,
        staged_document,
        RestorePlan(
            id="reviewed-plan",
            backup_id="synthetic-backup",
            categories={BackupCategory.DATABASE, BackupCategory.DOCUMENTS},
            staged_path=str(staged_root),
            file_count=2,
            fingerprint="b" * 64,
            status=RestoreStatus.STAGED,
            created_at=datetime.now(UTC),
        ),
    )


@pytest.mark.parametrize("status", ["PLANNED", "ACCEPTED", "UNCERTAIN", "FAILED", "CONFIRMED"])
@pytest.mark.parametrize("legacy", [False, True])
def test_backup_before_attempt_cannot_reopen_draft(
    restore: _Restore, status: str, legacy: bool
) -> None:
    if legacy:
        for path in (restore.current, restore.staged):
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("DROP TABLE mail_send_claims")
                connection.execute("UPDATE alembic_version SET version_num='20260814_0023'")
    # The staged backup was taken after review but before this provider attempt.
    _record(restore.current, status, claim=not legacy)
    restore.assert_refused()


@pytest.mark.parametrize("legacy", [False, True])
def test_exact_history_with_additional_staged_evidence_is_compatible(
    restore: _Restore, legacy: bool
) -> None:
    if legacy:
        with closing(sqlite3.connect(restore.current)) as connection, connection:
            connection.execute("DROP TABLE mail_send_claims")
            connection.execute("UPDATE alembic_version SET version_num='20260814_0023'")
    _record(restore.current, "UNCERTAIN", claim=not legacy)
    shutil.copyfile(restore.current, restore.staged)
    _record(restore.staged, "ACCEPTED", suffix="2", claim=not legacy)
    original = restore.current.read_bytes()
    expected = restore.staged.read_bytes()
    restore.apply()
    assert restore.current.read_bytes() == expected
    assert restore.current.with_suffix(".db.pre-restore").read_bytes() == original
    assert restore.document.read_bytes() == b"staged encrypted document"


@pytest.mark.parametrize("column", _AUDIT_COLUMNS)
def test_restore_cannot_change_any_recorded_audit_evidence(restore: _Restore, column: str) -> None:
    _record(restore.current)
    shutil.copyfile(restore.current, restore.staged)
    with closing(sqlite3.connect(restore.staged)) as connection, connection:
        connection.execute(f"UPDATE communication_mutation_audits SET {column} = ?", ("changed",))
    restore.assert_refused()


@pytest.mark.parametrize("target", ["current", "staged"])
@pytest.mark.parametrize(
    "malformation",
    [
        "missing_audits",
        "missing_claims",
        "both_missing",
        "audit_view",
        "claim_view",
        "audit_column",
        "claim_column",
        "orphan",
        "mismatched_claim",
        "duplicate_audit",
        "duplicate_key",
        "duplicate_claim",
        "oversized_value",
        "huge_value",
        "null_kind",
    ],
)
def test_partial_or_uninspectable_mail_history_fails_closed(
    restore: _Restore,
    target: str,
    malformation: str,
) -> None:
    _record(restore.current)
    shutil.copyfile(restore.current, restore.staged)
    path = restore.current if target == "current" else restore.staged
    with closing(sqlite3.connect(path)) as connection, connection:
        if malformation in {"missing_audits", "both_missing", "audit_view", "audit_column"}:
            connection.execute("DROP TABLE communication_mutation_audits")
        if malformation in {"missing_claims", "both_missing", "claim_view", "claim_column"}:
            connection.execute("DROP TABLE mail_send_claims")
        if malformation == "audit_view":
            connection.execute(
                "CREATE VIEW communication_mutation_audits AS SELECT 'SEND_MESSAGE' AS kind"
            )
        if malformation == "claim_view":
            connection.execute("CREATE VIEW mail_send_claims AS SELECT 'draft-1' AS draft_id")
        if malformation == "audit_column":
            connection.execute("CREATE TABLE communication_mutation_audits (kind TEXT)")
        if malformation == "claim_column":
            connection.execute("CREATE TABLE mail_send_claims (draft_id TEXT)")
        if malformation == "orphan":
            connection.execute("DELETE FROM communication_mutation_audits")
        if malformation == "mismatched_claim":
            connection.execute("UPDATE mail_send_claims SET draft_id='other-draft'")
        if malformation == "duplicate_audit":
            connection.execute(
                "INSERT INTO communication_mutation_audits "
                "SELECT * FROM communication_mutation_audits"
            )
        if malformation == "duplicate_key":
            _attempt(connection, "FAILED", suffix="2")
            connection.execute("UPDATE communication_mutation_audits SET idempotency_key='key-1'")
        if malformation == "duplicate_claim":
            connection.execute("INSERT INTO mail_send_claims SELECT * FROM mail_send_claims")
        if malformation in {"oversized_value", "huge_value"}:
            connection.execute(
                "UPDATE communication_mutation_audits SET provider_resource_id=?",
                ("x" * (501 if malformation == "oversized_value" else 70_000),),
            )
        if malformation == "null_kind":
            connection.execute("UPDATE communication_mutation_audits SET kind=NULL")
    restore.assert_refused()


@pytest.mark.parametrize("contents", [None, b"corrupt synthetic staged database"])
def test_missing_or_corrupt_staged_database_cannot_discard_history(
    restore: _Restore, contents: bytes | None
) -> None:
    _record(restore.current)
    if contents is None:
        restore.staged.unlink()
    else:
        restore.staged.write_bytes(contents)
    restore.assert_refused()


@pytest.mark.parametrize("target", ["current", "staged"])
def test_history_row_bound_fails_closed(
    restore: _Restore, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    _record(restore.current)
    shutil.copyfile(restore.current, restore.staged)
    _record(restore.current if target == "current" else restore.staged, suffix="2")
    monkeypatch.setattr("job_apply_pro.services.backup._MAIL_RESTORE_MAX_ROWS", 1)
    restore.assert_refused()


def test_inspection_is_read_only_and_includes_committed_wal_attempt(restore: _Restore) -> None:
    with closing(sqlite3.connect(restore.current)) as keeper:
        assert keeper.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        keeper.execute("PRAGMA wal_autocheckpoint=0")
        _attempt(keeper, "UNCERTAIN")
        keeper.commit()
        wal = restore.current.with_name(restore.current.name + "-wal")
        original_wal = wal.read_bytes()
        assert b"UNCERTAIN" not in restore.current.read_bytes()
        assert b"UNCERTAIN" in original_wal
        connect = sqlite3.connect
        with patch("job_apply_pro.services.backup.sqlite3.connect", wraps=connect) as observed:
            restore.assert_refused()
        for call in observed.call_args_list:
            assert call.args[0].endswith("?mode=ro")
            assert "immutable" not in call.args[0]
            assert call.kwargs["uri"] is True
        assert wal.read_bytes() == original_wal


def test_unreadable_mail_history_error_is_static(restore: _Restore) -> None:
    _record(restore.current)
    with (
        patch(
            "job_apply_pro.services.backup.sqlite3.connect",
            side_effect=sqlite3.OperationalError("synthetic private database path"),
        ),
        pytest.raises(BackupError) as error,
    ):
        BackupService._require_preserved_mail_attempts(restore.current, restore.staged)
    assert (
        str(error.value) == "Mail send history cannot be inspected safely; restore was not applied"
    )


def test_documents_only_restore_does_not_consult_mail_history(restore: _Restore) -> None:
    _record(restore.current)
    original = restore.current.read_bytes()
    document_plan = restore.plan.model_copy(update={"categories": {BackupCategory.DOCUMENTS}})
    with patch.object(BackupService, "_require_preserved_mail_attempts") as guard:
        BackupService.apply_staged_files(
            document_plan,
            database_url=f"sqlite:///{restore.current.as_posix()}",
            document_dir=restore.document.parent,
            staging_dir=Path(restore.plan.staged_path).parent,
        )
    guard.assert_not_called()
    assert restore.current.read_bytes() == original
    assert restore.document.read_bytes() == b"staged encrypted document"


@pytest.mark.parametrize("revision", [None, "20260805_0007"])
def test_valid_pre_mail_schema_has_no_send_evidence_to_preserve(
    restore: _Restore, revision: str | None
) -> None:
    with closing(sqlite3.connect(restore.current)) as connection, connection:
        connection.execute("DROP TABLE mail_send_claims")
        connection.execute("DROP TABLE communication_mutation_audits")
        if revision is None:
            connection.execute("DROP TABLE alembic_version")
        else:
            connection.execute("UPDATE alembic_version SET version_num=?", (revision,))
    restore.apply()
    assert restore.current.read_bytes() == restore.staged.read_bytes()


def test_current_schema_without_attempts_is_compatible(restore: _Restore) -> None:
    restore.apply()
    assert restore.current.read_bytes() == restore.staged.read_bytes()


def test_matching_audit_does_not_allow_discarding_its_claim(restore: _Restore) -> None:
    _record(restore.current)
    shutil.copyfile(restore.current, restore.staged)
    with closing(sqlite3.connect(restore.staged)) as connection, connection:
        connection.execute("DELETE FROM mail_send_claims")
    restore.assert_refused()


@pytest.mark.parametrize("uncertain", [False, True])
def test_real_encrypted_backup_before_send_preserves_current_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    uncertain: bool,
) -> None:
    database = tmp_path / "actual-schema.db"
    database_url = f"sqlite:///{database.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    calls = 0

    def ambiguous_send(*args: object, **kwargs: object) -> ProviderMailResult:
        nonlocal calls
        calls += 1
        raise ProviderSendUncertainError()

    with Session(engine) as session:
        mail, _, adapter, analysis_id = _service(session, IntegrationProvider.GMAIL)
        draft = mail.create_draft(
            _command(
                IntegrationProvider.GMAIL,
                analysis_id=analysis_id,
                attachments=False,
            )
        )
        backup = BackupService(
            OperationsRepository(session),
            SensitiveDataCipher(StaticKeyProvider(b"r" * 32)),
            database_url=database_url,
            document_dir=tmp_path / "documents",
            backup_dir=tmp_path / "backups",
            staging_dir=tmp_path / "staging",
        )
        manifest = backup.create(BackupCreate(categories={BackupCategory.DATABASE}))
        if uncertain:
            monkeypatch.setattr(adapter, "send", ambiguous_send)
        audit = mail.send_draft(draft.id, _confirmation(draft))
        assert audit.status is (MutationStatus.UNCERTAIN if uncertain else MutationStatus.ACCEPTED)
        plan = backup.stage_restore(
            manifest.id, RestoreCreate(categories={BackupCategory.DATABASE})
        )
    engine.dispose()
    before = database.read_bytes()
    with pytest.raises(BackupError, match="recorded mail send attempts"):
        BackupService.apply_staged_files(
            plan,
            database_url=database_url,
            document_dir=tmp_path / "documents",
            staging_dir=tmp_path / "staging",
        )
    assert database.read_bytes() == before
    assert not database.with_suffix(".db.pre-restore").exists()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT draft_id, audit_id FROM mail_send_claims").fetchall() == [
            (draft.id, audit.id),
        ]
        assert connection.execute(
            "SELECT status FROM communication_mutation_audits"
        ).fetchone() == (audit.status.value,)
    assert calls == (1 if uncertain else 0)
    assert len(adapter.sent) == (0 if uncertain else 1)
