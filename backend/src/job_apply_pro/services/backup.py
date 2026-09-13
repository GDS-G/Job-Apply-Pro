from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import uuid4

from job_apply_pro import __version__
from job_apply_pro.domain.operations import (
    BackupCategory,
    BackupCreate,
    BackupEntry,
    BackupManifest,
    BackupSchedule,
    BackupScheduleCreate,
    BackupStatus,
    BackupVerification,
    RestoreConfirmation,
    RestoreCreate,
    RestorePlan,
    RestoreStatus,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.storage.operations_repository import OperationsRepository

_MAIL_RESTORE_MAX_ROWS = 10_000
_MAIL_AUDIT_COLUMNS = (
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
_MAIL_AUDIT_LIMITS = (100, 40, 40, 100, 200, 64, 30, 200, 500, 100, 64)
_PRE_MAIL_REVISIONS = {f"20260805_{number:04d}" for number in range(1, 8)}
_PRE_CLAIM_MAIL_REVISIONS = {
    "20260805_0008",
    "20260805_0009",
    "20260811_0010",
    "20260811_0011",
    "20260811_0012",
    "20260811_0013",
    "20260811_0014",
    "20260811_0015",
    "20260812_0016",
    "20260812_0017",
    "20260812_0018",
    "20260812_0019",
    "20260812_0020",
    "20260812_0021",
    "20260812_0022",
    "20260814_0023",
}


class BackupError(RuntimeError):
    pass


class CloudBackupProvider(Protocol):
    def upload_encrypted(self, manifest: BackupManifest, archive: bytes) -> str: ...


class CloudBackupNotConfiguredError(RuntimeError):
    pass


class DisabledCloudBackupProvider:
    def upload_encrypted(self, manifest: BackupManifest, archive: bytes) -> str:
        del manifest, archive
        raise CloudBackupNotConfiguredError("Encrypted cloud backup is not configured")


class BackupService:
    SCHEMA_REVISION = "20260913_0024"
    RESTORE_PHRASE = "APPLY VERIFIED RESTORE"

    def __init__(
        self,
        repository: OperationsRepository,
        cipher: SensitiveDataCipher,
        *,
        database_url: str,
        document_dir: Path,
        backup_dir: Path,
        staging_dir: Path,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._database_path = self._sqlite_path(database_url)
        self._document_dir = document_dir.resolve()
        self._backup_dir = backup_dir.resolve()
        self._staging_dir = staging_dir.resolve()
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._staging_dir.mkdir(parents=True, exist_ok=True)

    def create(self, command: BackupCreate) -> BackupManifest:
        if not command.categories:
            raise ValueError("At least one backup category is required")
        backup_id = str(uuid4())
        created_at = datetime.now(UTC)
        files = self._collect_files(command.categories)
        entries = [
            BackupEntry(
                category=category,
                relative_path=relative_path,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
            for category, relative_path, data in files
        ]
        archive = self._build_zip(backup_id, command.label, created_at, files, entries)
        envelope = self._cipher.encrypt_bytes(archive, context=f"backup:{backup_id}:archive")
        target = self._backup_dir / f"{backup_id}.japbackup"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(envelope, encoding="ascii")
        temporary.replace(target)
        encoded = envelope.encode("ascii")
        manifest = BackupManifest(
            id=backup_id,
            application_version=__version__,
            schema_revision=self.SCHEMA_REVISION,
            label=command.label,
            categories=command.categories,
            entries=entries,
            encryption_key_id=self._cipher.key_id,
            archive_path=str(target),
            archive_sha256=hashlib.sha256(encoded).hexdigest(),
            archive_size_bytes=len(encoded),
            status=BackupStatus.CREATING,
            created_at=created_at,
        )
        self._repository.save_backup(manifest)
        verification = self.verify(backup_id)
        if not verification.valid:
            self._repository.save_backup(
                manifest.model_copy(
                    update={
                        "status": BackupStatus.FAILED,
                        "verified_at": verification.verified_at,
                    }
                )
            )
            raise BackupError("New backup failed integrity verification")
        verified = manifest.model_copy(
            update={
                "status": BackupStatus.VERIFIED,
                "verified_at": verification.verified_at,
            }
        )
        return self._repository.save_backup(verified)

    def verify(self, backup_id: str) -> BackupVerification:
        manifest = self._require_backup(backup_id)
        reasons: list[str] = []
        verified_entries = 0
        path = Path(manifest.archive_path)
        if not path.is_file():
            reasons.append("ARCHIVE_NOT_FOUND")
        else:
            encoded = path.read_bytes()
            if hashlib.sha256(encoded).hexdigest() != manifest.archive_sha256:
                reasons.append("ARCHIVE_HASH_MISMATCH")
            else:
                try:
                    archive = self._cipher.decrypt_bytes(
                        encoded.decode("ascii"), context=f"backup:{backup_id}:archive"
                    )
                    verified_entries = self._verify_zip(archive, manifest, reasons)
                except (UnicodeDecodeError, ValueError, zipfile.BadZipFile):
                    reasons.append("ARCHIVE_AUTHENTICATION_FAILED")
        return BackupVerification(
            backup_id=backup_id,
            valid=not reasons,
            reasons=reasons,
            verified_entries=verified_entries,
            verified_at=datetime.now(UTC),
        )

    def stage_restore(self, backup_id: str, command: RestoreCreate) -> RestorePlan:
        manifest = self._require_backup(backup_id)
        if not command.categories or not command.categories.issubset(manifest.categories):
            raise ValueError("Restore categories must be present in the selected backup")
        verification = self.verify(backup_id)
        if not verification.valid:
            raise BackupError("Backup failed integrity verification")
        archive = self._cipher.decrypt_bytes(
            Path(manifest.archive_path).read_text(encoding="ascii"),
            context=f"backup:{backup_id}:archive",
        )
        plan_id = str(uuid4())
        target = self._staging_dir / plan_id
        target.mkdir(parents=True, exist_ok=False)
        count = 0
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            entry_by_path = {entry.relative_path: entry for entry in manifest.entries}
            for name in bundle.namelist():
                if name == "manifest.json":
                    continue
                entry = entry_by_path.get(name)
                if entry is None or entry.category not in command.categories:
                    continue
                safe = self._safe_relative(name)
                output = (target / safe).resolve()
                if target not in output.parents:
                    raise BackupError("Backup contains an unsafe path")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(bundle.read(name))
                count += 1
        fingerprint = self._fingerprint(
            {
                "plan_id": plan_id,
                "backup_id": backup_id,
                "categories": sorted(value.value for value in command.categories),
                "archive_sha256": manifest.archive_sha256,
                "file_count": count,
            }
        )
        return self._repository.save_restore_plan(
            RestorePlan(
                id=plan_id,
                backup_id=backup_id,
                categories=command.categories,
                staged_path=str(target),
                file_count=count,
                fingerprint=fingerprint,
                status=RestoreStatus.STAGED,
                created_at=datetime.now(UTC),
            )
        )

    def apply_offline(self, plan_id: str, command: RestoreConfirmation) -> RestorePlan:
        plan = self._repository.get_restore_plan(plan_id)
        if plan is None:
            raise LookupError(f"Restore plan {plan_id} was not found")
        if command.fingerprint != plan.fingerprint:
            raise ValueError("Restore plan changed after review")
        if command.confirmation_phrase != self.RESTORE_PHRASE:
            raise ValueError(f"confirmation_phrase must be {self.RESTORE_PHRASE}")
        self.apply_staged_files(
            plan,
            database_url=f"sqlite:///{self._database_path.as_posix()}",
            document_dir=self._document_dir,
            staging_dir=self._staging_dir,
        )
        applied = plan.model_copy(
            update={"status": RestoreStatus.APPLIED, "applied_at": datetime.now(UTC)}
        )
        return self._repository.save_restore_plan(applied)

    @classmethod
    def apply_staged_files(
        cls,
        plan: RestorePlan,
        *,
        database_url: str,
        document_dir: Path,
        staging_dir: Path,
    ) -> None:
        """Apply verified staged files only with the API and media worker stopped.

        The desktop supervisor waits for the API process to exit, then its restore
        CLI closes database handles before calling here. The journal check below
        is a read-only offline precondition, not serialization against live writers.
        """
        staged = Path(plan.staged_path).resolve()
        staging_root = staging_dir.resolve()
        if not staged.is_dir() or staging_root not in staged.parents:
            raise BackupError("Restore staging directory is unavailable")
        if BackupCategory.DATABASE in plan.categories:
            source = staged / "database" / "job_apply_pro.db"
            target_database = cls._sqlite_path(database_url)
            cls._require_resolved_media_cleanup(target_database)
            cls._require_preserved_mail_attempts(target_database, source)
            cls._atomic_restore(source, target_database, preserve_previous=True)
        if BackupCategory.DOCUMENTS in plan.categories:
            source_root = staged / "documents"
            if not source_root.is_dir():
                raise BackupError("Staged restore documents are missing")
            target_root = document_dir.resolve()
            for source in source_root.rglob("*"):
                if source.is_file() and not source.is_symlink():
                    relative = source.relative_to(source_root)
                    cls._atomic_restore(source, target_root / relative, preserve_previous=False)

    @staticmethod
    def _require_resolved_media_cleanup(database_path: Path) -> None:
        """Never discard current provider cleanup obligations during offline restore."""
        try:
            if not database_path.is_file():
                raise OSError("Current database is unavailable")
            # Do not use immutable=1: it can ignore committed journal rows in WAL.
            # mode=ro prohibits main-database writes and refuses a missing main database;
            # SQLite may still use shared-memory coordination sidecars.
            with closing(
                sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True, timeout=1.0)
            ) as connection:
                journal = connection.execute(
                    "SELECT type FROM sqlite_master WHERE name = 'ai_media_cleanup' COLLATE NOCASE"
                ).fetchone()
                if journal is None:
                    # A valid legacy database predating the media journal is safe.
                    return
                if journal != ("table",):
                    raise sqlite3.DatabaseError("Media cleanup journal is not a table")
                unresolved = connection.execute(
                    "SELECT 1 FROM ai_media_cleanup "
                    "WHERE state IS NULL OR state COLLATE BINARY != ? LIMIT 1",
                    ("DELETED",),
                ).fetchone()
        except (OSError, sqlite3.Error):
            raise BackupError(
                "Current database cannot be inspected safely for provider media cleanup; "
                "restore was not applied"
            ) from None
        if unresolved is not None:
            raise BackupError(
                "Database restore is blocked by unresolved provider media cleanup; "
                "complete recovery or verified manual review before restoring"
            )

    @classmethod
    def _require_preserved_mail_attempts(
        cls, current_database: Path, staged_database: Path
    ) -> None:
        """Offline precondition: a restore must not reopen an already attempted mail draft.

        All recorded outcomes are retained exactly, including legacy CONFIRMED,
        failed and unconfirmed reservations. This is not a merge or a lock against
        live writers. A valid current database with no mail evidence has nothing
        for this guard to preserve; staged-file integrity remains a separate check.
        """
        try:
            current_audits, current_claims = cls._mail_restore_evidence(current_database)
            if not current_audits and not current_claims:
                return
            staged_audits, staged_claims = cls._mail_restore_evidence(staged_database)
        except (OSError, ValueError, sqlite3.Error):
            raise BackupError(
                "Mail send history cannot be inspected safely; restore was not applied"
            ) from None
        if any(staged_audits.get(key) != row for key, row in current_audits.items()) or not (
            current_claims <= staged_claims
        ):
            raise BackupError(
                "Database restore would discard or change recorded mail send attempts; "
                "use a backup containing the same send history"
            )

    @staticmethod
    def _mail_restore_evidence(
        database_path: Path,
    ) -> tuple[dict[str, tuple[str | None, ...]], set[tuple[str, str]]]:
        if not database_path.is_file():
            raise OSError("Database unavailable")
        # mode=ro (not immutable=1) includes committed WAL evidence and refuses creation
        # of a missing main database; SQLite may use shared-memory coordination sidecars.
        with closing(
            sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True, timeout=1.0)
        ) as connection:
            # Bound each SQLite value/row before Python materializes it. Individual
            # audit values are checked more narrowly below; no bytes/content are read.
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 65_536)

            def table_exists(name: str) -> bool:
                rows = connection.execute(
                    "SELECT type FROM sqlite_master WHERE name = ? COLLATE NOCASE", (name,)
                ).fetchmany(2)
                if rows and rows != [("table",)]:
                    raise ValueError("Invalid history schema")
                return bool(rows)

            revision = None
            if table_exists("alembic_version"):
                revisions = connection.execute("SELECT version_num FROM alembic_version").fetchmany(
                    2
                )
                if len(revisions) != 1 or not isinstance(revisions[0][0], str):
                    raise ValueError("Invalid schema revision")
                revision = revisions[0][0]
            has_audits = table_exists("communication_mutation_audits")
            has_claims = table_exists("mail_send_claims")
            if not has_audits:
                if has_claims or (revision is not None and revision not in _PRE_MAIL_REVISIONS):
                    raise ValueError("Missing history table")
                return {}, set()
            if not has_claims and revision not in _PRE_CLAIM_MAIL_REVISIONS:
                raise ValueError("Missing claim table")

            audits: dict[str, tuple[str | None, ...]] = {}
            seen_ids: set[str] = set()
            seen_keys: set[str] = set()
            rows = connection.execute(
                f"SELECT {', '.join(_MAIL_AUDIT_COLUMNS)} FROM communication_mutation_audits "
                "LIMIT ?",
                (_MAIL_RESTORE_MAX_ROWS + 1,),
            )
            for index, row in enumerate(rows):
                if index >= _MAIL_RESTORE_MAX_ROWS:
                    raise ValueError("History inspection exceeds the bounded limit")
                values: list[str | None] = []
                for column, (value, limit) in enumerate(zip(row, _MAIL_AUDIT_LIMITS, strict=True)):
                    if value is None and column in {7, 8, 9}:
                        values.append(None)
                    elif not isinstance(value, str) or not value or len(value) > limit:
                        raise ValueError("Invalid history value")
                    else:
                        values.append(value)
                audit_id, kind, _, _, key = values[:5]
                assert audit_id is not None and key is not None
                if (
                    audit_id in seen_ids
                    or key in seen_keys
                    or kind
                    not in {"SEND_MESSAGE", "CREATE_CALENDAR_EVENT", "UPDATE_CALENDAR_EVENT"}
                ):
                    raise ValueError("Ambiguous history identity")
                seen_ids.add(audit_id)
                seen_keys.add(key)
                if kind == "SEND_MESSAGE":
                    audits[audit_id] = tuple(values)
            claims: set[tuple[str, str]] = set()
            if has_claims:
                seen_drafts: set[str] = set()
                seen_audits: set[str] = set()
                for index, row in enumerate(
                    connection.execute(
                        "SELECT draft_id, audit_id FROM mail_send_claims LIMIT ?",
                        (_MAIL_RESTORE_MAX_ROWS + 1,),
                    )
                ):
                    if index >= _MAIL_RESTORE_MAX_ROWS:
                        raise ValueError("Claim inspection exceeds the bounded limit")
                    draft_id, audit_id = row
                    if (
                        not isinstance(draft_id, str)
                        or not 0 < len(draft_id) <= 100
                        or not isinstance(audit_id, str)
                        or not 0 < len(audit_id) <= 100
                        or draft_id in seen_drafts
                        or audit_id in seen_audits
                        or audit_id not in audits
                        or audits[audit_id][3] != draft_id
                    ):
                        raise ValueError("Invalid claim evidence")
                    seen_drafts.add(draft_id)
                    seen_audits.add(audit_id)
                    claims.add((draft_id, audit_id))
            return audits, claims

    def list_backups(self) -> list[BackupManifest]:
        return self._repository.list_backups()

    def create_schedule(self, command: BackupScheduleCreate) -> BackupSchedule:
        if not command.categories:
            raise ValueError("At least one scheduled backup category is required")
        now = datetime.now(UTC)
        return self._repository.save_schedule(
            BackupSchedule(
                id=str(uuid4()),
                **command.model_dump(),
                next_run_at=now + timedelta(hours=command.interval_hours),
                created_at=now,
                updated_at=now,
            )
        )

    def list_schedules(self) -> list[BackupSchedule]:
        return self._repository.list_schedules()

    def run_due_schedules(self, *, now: datetime | None = None) -> list[BackupManifest]:
        current = now or datetime.now(UTC)
        created: list[BackupManifest] = []
        for schedule in self.list_schedules():
            if not schedule.enabled or schedule.next_run_at > current:
                continue
            created.append(
                self.create(BackupCreate(categories=schedule.categories, label=schedule.label))
            )
            self._repository.save_schedule(
                schedule.model_copy(
                    update={
                        "last_run_at": current,
                        "next_run_at": current + timedelta(hours=schedule.interval_hours),
                        "updated_at": current,
                    }
                )
            )
        return created

    def _collect_files(
        self, categories: set[BackupCategory]
    ) -> list[tuple[BackupCategory, str, bytes]]:
        files: list[tuple[BackupCategory, str, bytes]] = []
        if BackupCategory.DATABASE in categories:
            files.append(
                (
                    BackupCategory.DATABASE,
                    "database/job_apply_pro.db",
                    self._snapshot_database(),
                )
            )
        if BackupCategory.DOCUMENTS in categories and self._document_dir.is_dir():
            for path in sorted(self._document_dir.rglob("*")):
                resolved = path.resolve()
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or self._document_dir not in resolved.parents
                ):
                    continue
                relative = resolved.relative_to(self._document_dir).as_posix()
                files.append((BackupCategory.DOCUMENTS, f"documents/{relative}", path.read_bytes()))
        return files

    def _snapshot_database(self) -> bytes:
        if not self._database_path.is_file():
            raise BackupError("SQLite database was not found")
        with tempfile.TemporaryDirectory(dir=self._backup_dir) as temporary:
            snapshot = Path(temporary) / "job_apply_pro.db"
            source = sqlite3.connect(self._database_path)
            destination = sqlite3.connect(snapshot)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            return snapshot.read_bytes()

    def _build_zip(
        self,
        backup_id: str,
        label: str,
        created_at: datetime,
        files: list[tuple[BackupCategory, str, bytes]],
        entries: list[BackupEntry],
    ) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "id": backup_id,
                        "format_version": 1,
                        "application_version": __version__,
                        "schema_revision": self.SCHEMA_REVISION,
                        "label": label,
                        "created_at": created_at.isoformat(),
                        "entries": [entry.model_dump(mode="json") for entry in entries],
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
            for _category, relative_path, data in files:
                bundle.writestr(relative_path, data)
        return output.getvalue()

    def _verify_zip(self, archive: bytes, manifest: BackupManifest, reasons: list[str]) -> int:
        verified = 0
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = set(bundle.namelist())
            if "manifest.json" not in names:
                reasons.append("MANIFEST_NOT_FOUND")
            else:
                try:
                    internal = json.loads(bundle.read("manifest.json"))
                    if (
                        internal.get("id") != manifest.id
                        or internal.get("application_version") != manifest.application_version
                        or internal.get("schema_revision") != manifest.schema_revision
                        or internal.get("entries")
                        != [entry.model_dump(mode="json") for entry in manifest.entries]
                    ):
                        reasons.append("MANIFEST_MISMATCH")
                except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                    reasons.append("MANIFEST_INVALID")
            for entry in manifest.entries:
                try:
                    self._safe_relative(entry.relative_path)
                except BackupError:
                    reasons.append("UNSAFE_ENTRY_PATH")
                    continue
                if entry.relative_path not in names:
                    reasons.append(f"ENTRY_NOT_FOUND:{entry.relative_path}")
                    continue
                data = bundle.read(entry.relative_path)
                if len(data) != entry.size_bytes:
                    reasons.append(f"ENTRY_SIZE_MISMATCH:{entry.relative_path}")
                elif hashlib.sha256(data).hexdigest() != entry.sha256:
                    reasons.append(f"ENTRY_HASH_MISMATCH:{entry.relative_path}")
                else:
                    verified += 1
        return verified

    def _require_backup(self, backup_id: str) -> BackupManifest:
        manifest = self._repository.get_backup(backup_id)
        if manifest is None:
            raise LookupError(f"Backup {backup_id} was not found")
        return manifest

    @staticmethod
    def _safe_relative(value: str) -> Path:
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise BackupError("Backup contains an unsafe path")
        return Path(*pure.parts)

    @staticmethod
    def _atomic_restore(source: Path, target: Path, *, preserve_previous: bool) -> None:
        if not source.is_file():
            raise BackupError(f"Staged restore file is missing: {source.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if preserve_previous and target.exists():
            shutil.copy2(target, target.with_suffix(target.suffix + ".pre-restore"))
        temporary = target.with_suffix(target.suffix + ".restore.tmp")
        shutil.copy2(source, temporary)
        temporary.replace(target)

    @staticmethod
    def _fingerprint(value: dict[str, object]) -> str:
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _sqlite_path(database_url: str) -> Path:
        prefix = "sqlite:///"
        if not database_url.startswith(prefix) or database_url == "sqlite:///:memory:":
            raise BackupError("Encrypted local backup currently requires a file-backed SQLite URL")
        return Path(database_url.removeprefix(prefix)).resolve()
