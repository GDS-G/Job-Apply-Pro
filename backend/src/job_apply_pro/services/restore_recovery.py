"""Authenticated completion admission, intentionally without rollback/resume."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from job_apply_pro.domain.operations import (
    BackupCategory,
    BackupManifest,
    RestorePlan,
    RestoreStatus,
)
from job_apply_pro.restore_admission import (
    assert_no_sqlite_sidecars,
    assert_restore_source_closed,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.storage.restore_gate_repository import (
    RECOVERY_MESSAGE,
    RestoreAdmissionError,
    RestoreGateRepository,
    checked_path,
    owns_restore,
    safe_relative,
    sync_directory,
    workspace_access,
    write_exclusive,
)

MAX_RESTORE_FILES = 4096
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_RESTORE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES = 384 * 1024 * 1024


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(ge=0, le=MAX_FILE_BYTES)


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    workspace: str
    database: str
    documents: str
    staged: str
    plan: RestorePlan
    manifest: BackupManifest
    inputs: list[Target] = Field(max_length=MAX_RESTORE_FILES)


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    intent_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    # Document-only restores also commit bookkeeping to the existing database.
    targets: list[Target] = Field(max_length=MAX_RESTORE_FILES + 1)


def hash_file(path: Path) -> tuple[str, int]:
    checked_path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RestoreAdmissionError("Restore requires regular, exclusively owned files")
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            count += len(block)
            if count > MAX_FILE_BYTES:
                raise RestoreAdmissionError("Restore file exceeds the supported 256 MiB bound")
            digest.update(block)
    return digest.hexdigest(), count


def _intent_hash(intent: Intent) -> str:
    value = intent.model_dump(mode="json")
    value["plan"]["categories"] = sorted(value["plan"]["categories"])
    value["manifest"]["categories"] = sorted(value["manifest"]["categories"])
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _authenticate_archive(
    archive: Path, manifest: BackupManifest, cipher: SensitiveDataCipher
) -> None:
    """Bind database metadata back to authenticated, bounded archive contents."""
    if (
        archive.stat().st_size != manifest.archive_size_bytes
        or manifest.archive_size_bytes > MAX_ARCHIVE_BYTES
    ):
        raise RestoreAdmissionError(
            "Reviewed backup archive changed or exceeds the supported 384 MiB bound"
        )
    encoded = archive.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != manifest.archive_sha256:
        raise RestoreAdmissionError("Reviewed backup archive changed")
    data = cipher.decrypt_bytes(encoded.decode("ascii"), context=f"backup:{manifest.id}:archive")
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        entries = bundle.infolist()
        if len(entries) > MAX_RESTORE_FILES + 1 or len(
            {entry.filename.casefold() for entry in entries}
        ) != len(entries):
            raise RestoreAdmissionError("Backup inventory exceeds its bound or has colliding paths")
        if (
            any(entry.file_size > MAX_FILE_BYTES for entry in entries)
            or sum(entry.file_size for entry in entries) > MAX_RESTORE_BYTES
        ):
            raise RestoreAdmissionError("Backup expanded contents exceed the supported bound")
        if {entry.filename for entry in entries} != {
            "manifest.json",
            *(entry.relative_path for entry in manifest.entries),
        }:
            raise RestoreAdmissionError("Backup inventory no longer matches its manifest")
        if bundle.getinfo("manifest.json").file_size > 4 * 1024 * 1024:
            raise RestoreAdmissionError("Backup metadata exceeds the supported bound")
        internal = json.loads(bundle.read("manifest.json"))
        if (
            not isinstance(internal, dict)
            or any(
                internal.get(field) != getattr(manifest, field)
                for field in (
                    "id",
                    "format_version",
                    "application_version",
                    "schema_revision",
                    "label",
                )
            )
            or internal.get("entries")
            != [entry.model_dump(mode="json") for entry in manifest.entries]
        ):
            raise RestoreAdmissionError("Backup authenticated manifest changed")
        for entry in manifest.entries:
            safe_relative(entry.relative_path)
            contents = bundle.read(entry.relative_path)
            if (
                len(contents) != entry.size_bytes
                or hashlib.sha256(contents).hexdigest() != entry.sha256
            ):
                raise RestoreAdmissionError(
                    "Backup entry failed authenticated integrity verification"
                )


class RestoreRecoveryService:
    def __init__(self, root: Path, cipher: SensitiveDataCipher) -> None:
        self.gate = RestoreGateRepository(root)
        self.cipher = cipher

    def prepare(
        self,
        plan: RestorePlan,
        manifest: BackupManifest,
        *,
        database: Path,
        documents: Path,
        staging: Path,
        backups: Path,
    ) -> Intent:
        root = self.gate.root
        if root == Path(root.anchor):
            raise RestoreAdmissionError("Restore requires a dedicated app-owned local workspace")
        database = checked_path(database, root=root)
        documents = checked_path(documents, root=root)
        staging = checked_path(staging, root=root)
        backups = checked_path(backups, root=root)
        if (
            database.parent != root
            or any(
                left == right or left in right.parents or right in left.parents
                for index, left in enumerate((documents, staging, backups, self.gate.control))
                for right in (documents, staging, backups, self.gate.control)[index + 1 :]
            )
            or any(
                directory == database or directory in database.parents
                for directory in (documents, staging, backups, self.gate.control)
            )
        ):
            raise RestoreAdmissionError(
                "Restore requires separate database, documents, backup, staging and control "
                "locations within the app workspace"
            )
        if str(UUID(plan.id)) != plan.id or str(UUID(plan.backup_id)) != plan.backup_id:
            raise RestoreAdmissionError("Restore plan identifiers are invalid")
        staged = checked_path(Path(plan.staged_path), root=staging)
        if staged != staging / plan.id or not staged.is_dir():
            raise RestoreAdmissionError("Staged restore directory is missing or changed")
        if (
            plan.status is not RestoreStatus.STAGED
            or manifest.id != plan.backup_id
            or not plan.categories
            or not plan.categories.issubset(manifest.categories)
        ):
            raise RestoreAdmissionError("Restore plan no longer matches the reviewed backup")
        archive = checked_path(Path(manifest.archive_path), root=backups)
        if archive != backups / f"{manifest.id}.japbackup":
            raise RestoreAdmissionError(
                "Backup archive location no longer matches its owned identifier"
            )
        _authenticate_archive(archive, manifest, self.cipher)
        from job_apply_pro.services.backup import BackupService

        if plan.fingerprint != BackupService._fingerprint(
            {
                "plan_id": plan.id,
                "backup_id": manifest.id,
                "categories": sorted(category.value for category in plan.categories),
                "archive_sha256": manifest.archive_sha256,
                "file_count": plan.file_count,
            }
        ):
            raise RestoreAdmissionError("Restore plan changed after review")
        entries = [entry for entry in manifest.entries if entry.category in plan.categories]
        if (
            len(entries) != plan.file_count
            or len(entries) > MAX_RESTORE_FILES
            or sum(entry.size_bytes for entry in entries) > MAX_RESTORE_BYTES
        ):
            raise RestoreAdmissionError("Restore inventory changed or exceeds its supported bound")
        inputs: list[Target] = []
        seen: set[str] = set()
        for entry in entries:
            relative = safe_relative(entry.relative_path)
            if entry.relative_path.casefold() in seen:
                raise RestoreAdmissionError("Restore contains colliding paths")
            seen.add(entry.relative_path.casefold())
            if (
                entry.category is BackupCategory.DATABASE
                and entry.relative_path != "database/job_apply_pro.db"
            ) or (
                entry.category is BackupCategory.DOCUMENTS
                and (len(relative.parts) < 2 or relative.parts[0] != "documents")
            ):
                raise RestoreAdmissionError("Restore entry does not match its category")
            source = checked_path(staged / relative, root=staged)
            actual_hash, size = hash_file(source)
            if actual_hash != entry.sha256 or size != entry.size_bytes:
                raise RestoreAdmissionError("Staged restore bytes changed after review")
            inputs.append(Target(path=entry.relative_path, sha256=actual_hash, size=size))
            destination = (
                database
                if entry.category is BackupCategory.DATABASE
                else documents / Path(*relative.parts[1:])
            )
            checked_path(destination, root=root)
            if destination.exists():
                hash_file(destination)
        actual: set[str] = set()
        for path in staged.rglob("*"):
            checked_path(path, root=staged)
            if path.is_file():
                actual.add(path.relative_to(staged).as_posix())
                if len(actual) > MAX_RESTORE_FILES:
                    raise RestoreAdmissionError("Restore inventory exceeds its supported bound")
        if actual != {entry.path for entry in inputs}:
            raise RestoreAdmissionError(
                "Staged restore files are missing or were added after review"
            )
        return Intent(
            workspace=str(root),
            database=database.relative_to(root).as_posix(),
            documents=documents.relative_to(root).as_posix(),
            staged=staged.relative_to(root).as_posix(),
            plan=plan,
            manifest=manifest,
            inputs=inputs,
        )

    def apply(self, intent: Intent, commit_result: Callable[[RestorePlan], None]) -> RestorePlan:
        root = self.gate.root
        if not owns_restore(root):
            raise RestoreAdmissionError("Offline restore requires exclusive workspace ownership")
        self.gate.assert_clear()
        database = checked_path(root / safe_relative(intent.database), root=root)
        # Do not open SQLite at all while unknown journal sidecars exist. A
        # read-only SQLite connection is not an authorization to discard them.
        assert_no_sqlite_sidecars(database)
        hash_file(database)
        if BackupCategory.DATABASE in intent.plan.categories:
            from job_apply_pro.services.backup import BackupService

            BackupService._require_resolved_media_cleanup(database)
            staged_database = checked_path(
                root / safe_relative(intent.staged) / "database" / "job_apply_pro.db", root=root
            )
            assert_restore_source_closed(staged_database)
            # Local admission does not replace durable external-effect evidence.
            # A snapshot must preserve every current immutable mail attempt/claim.
            BackupService._require_preserved_mail_attempts(database, staged_database)
        operation_id = self.gate.begin(intent.model_dump(mode="json"), self.cipher)
        if BackupCategory.DATABASE in intent.plan.categories:
            # Unique encrypted DB preimage; never overwrite/delete a prior recovery copy.
            preimage = self.cipher.encrypt_bytes(
                database.read_bytes(), context=f"restore:v1:{operation_id}:database-preimage"
            )
            write_exclusive(
                self.gate.operation_path(operation_id) / "database-preimage.enc",
                preimage.encode("ascii"),
            )
        for source in intent.inputs:
            target = self._destination(intent, source)
            self._replace(
                root / safe_relative(intent.staged) / safe_relative(source.path),
                target,
                source,
                operation_id,
            )
        applied = intent.plan.model_copy(
            update={"status": RestoreStatus.APPLIED, "applied_at": datetime.now(UTC)}
        )
        commit_result(applied)
        targets = []
        for source in intent.inputs:
            target = self._destination(intent, source)
            digest, size = hash_file(target)
            if source.path != "database/job_apply_pro.db" and (
                digest != source.sha256 or size != source.size
            ):
                raise RestoreAdmissionError(RECOVERY_MESSAGE)
            if source.path == "database/job_apply_pro.db":
                assert_no_sqlite_sidecars(target)
            targets.append(
                Target(path=target.relative_to(root).as_posix(), sha256=digest, size=size)
            )
        # Even document-only restores update their manifest/plan in this database.
        # Completion therefore always proves the committed database bytes too.
        if BackupCategory.DATABASE not in intent.plan.categories:
            assert_no_sqlite_sidecars(database)
            digest, size = hash_file(database)
            targets.append(Target(path=intent.database, sha256=digest, size=size))
        receipt = Receipt(intent_sha256=_intent_hash(intent), targets=targets)
        self.gate.write_record(
            operation_id, "receipt", receipt.model_dump(mode="json"), self.cipher
        )
        self.finalize(operation_id)
        return applied

    def finalize(self, operation_id: str) -> None:
        with workspace_access(self.gate.root, restore=True):
            if self.gate.active_id() != operation_id:
                raise RestoreAdmissionError(RECOVERY_MESSAGE)
            intent = Intent.model_validate(
                self.gate.read_record(operation_id, "intent", self.cipher)
            )
            receipt = Receipt.model_validate(
                self.gate.read_record(operation_id, "receipt", self.cipher)
            )
            if intent.workspace != str(self.gate.root) or receipt.intent_sha256 != _intent_hash(
                intent
            ):
                raise RestoreAdmissionError(RECOVERY_MESSAGE)
            expected = [
                self._destination(intent, source).relative_to(self.gate.root).as_posix()
                for source in intent.inputs
            ]
            if BackupCategory.DATABASE not in intent.plan.categories:
                expected.append(intent.database)
            if [target.path for target in receipt.targets] != expected or len(
                {path.casefold() for path in expected}
            ) != len(expected):
                raise RestoreAdmissionError(RECOVERY_MESSAGE)
            for target in receipt.targets:
                path = checked_path(
                    self.gate.root / safe_relative(target.path), root=self.gate.root
                )
                if target.path == intent.database:
                    assert_no_sqlite_sidecars(path)
                else:
                    source = next(
                        source
                        for source in intent.inputs
                        if self._destination(intent, source) == path
                    )
                    if target.sha256 != source.sha256 or target.size != source.size:
                        raise RestoreAdmissionError(RECOVERY_MESSAGE)
                if hash_file(path) != (target.sha256, target.size):
                    raise RestoreAdmissionError(RECOVERY_MESSAGE)
            self.gate.finish_verified(operation_id)

    def _destination(self, intent: Intent, source: Target) -> Path:
        path = (
            safe_relative(intent.database)
            if source.path == "database/job_apply_pro.db"
            else safe_relative(intent.documents) / Path(*safe_relative(source.path).parts[1:])
        )
        return checked_path(self.gate.root / path, root=self.gate.root)

    def _replace(self, source: Path, target: Path, expected: Target, operation_id: str) -> None:
        checked_path(source, root=self.gate.root)
        checked_path(target, root=self.gate.root)
        info = source.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RestoreAdmissionError("Restore requires regular, exclusively owned inputs")
        if target.exists():
            info = target.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RestoreAdmissionError("Restore requires regular, exclusively owned targets")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{operation_id}.{uuid4()}.restore.tmp")
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as reader, temporary.open("xb") as writer:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                size += len(block)
                if size > expected.size:
                    raise RestoreAdmissionError("Staged restore bytes changed during replacement")
                digest.update(block)
                writer.write(block)
            writer.flush()
            os.fsync(writer.fileno())
        if size != expected.size or digest.hexdigest() != expected.sha256:
            raise RestoreAdmissionError("Staged restore bytes changed during replacement")
        checked_path(target, root=self.gate.root)
        temporary.replace(target)
        sync_directory(target.parent)
