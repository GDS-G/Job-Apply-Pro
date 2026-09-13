"""Version-two interrupted-operation rollback; never a general history merge."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from job_apply_pro.domain.operations import BackupCategory, RestorePlan, RestoreStatus
from job_apply_pro.restore_admission import assert_no_sqlite_sidecars, assert_restore_source_closed
from job_apply_pro.services.restore_recovery import (
    MAX_FILE_BYTES,
    MAX_RESTORE_BYTES,
    MAX_RESTORE_FILES,
    Intent,
    hash_file,
)
from job_apply_pro.storage.restore_gate_repository import (
    RECOVERY_MESSAGE,
    RestoreAdmissionError,
    atomic_write_exclusive,
    checked_path,
    owns_restore,
    safe_relative,
    sync_directory,
    workspace_access,
)

if TYPE_CHECKING:
    from job_apply_pro.services.restore_recovery import RestoreRecoveryService

POLICY: Literal["interrupted-restore-rollback/2"] = "interrupted-restore-rollback/2"
MAX_OBJECT_BYTES = 2 * MAX_FILE_BYTES + 4096


class RecoveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Image(RecoveryModel):
    name: str = Field(pattern=r"^[a-f0-9]{64}\.(before|after)\.enc$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(ge=0, le=MAX_FILE_BYTES)


class Replacement(RecoveryModel):
    path: str = Field(min_length=1, max_length=512)
    before: Image | None
    after: Image


class PreparedRestore(RecoveryModel):
    version: Literal[2] = 2
    policy: Literal["interrupted-restore-rollback/2"] = POLICY
    operation_id: str
    workspace: str
    source: Intent
    applied_plan: RestorePlan
    targets: list[Replacement] = Field(min_length=1, max_length=MAX_RESTORE_FILES + 1)


class RollbackDecision(RecoveryModel):
    version: Literal[2] = 2
    intent_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["ROLLBACK"] = "ROLLBACK"


class TerminalReceipt(RecoveryModel):
    version: Literal[2] = 2
    intent_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["APPLIED", "ROLLED_BACK"]
    # Absence is itself part of an authenticated rollback outcome.
    targets: list[tuple[str, str | None, int | None]] = Field(max_length=MAX_RESTORE_FILES + 1)


def digest_model(value: BaseModel) -> str:
    # Sets in the original staged plan have a deterministic canonical encoding.
    payload = value.model_dump(mode="json")
    if isinstance(value, PreparedRestore):
        payload["source"]["plan"]["categories"].sort()
        payload["source"]["manifest"]["categories"].sort()
        payload["applied_plan"]["categories"].sort()
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class RestoreRollback:
    def __init__(self, host: RestoreRecoveryService) -> None:
        self.host = host
        self.gate = host.gate
        self.cipher = host.cipher

    def _object_path(self, operation_id: str, image: Image) -> Path:
        return checked_path(
            self.gate.operation_path(operation_id) / "objects" / image.name,
            root=self.gate.root,
        )

    def _read_image(self, operation_id: str, image: Image) -> bytes:
        path = self._object_path(operation_id, image)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_OBJECT_BYTES:
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        with path.open("rb") as stream:
            encoded = stream.read(MAX_OBJECT_BYTES + 1)
        if len(encoded) > MAX_OBJECT_BYTES:
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        value = self.cipher.decrypt_bytes(
            encoded.decode("ascii"), context=f"restore:v2:{operation_id}:object:{image.name}"
        )
        if len(value) != image.size or hashlib.sha256(value).hexdigest() != image.sha256:
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        return value

    def _save_image(self, operation_id: str, path: str, side: str, value: bytes) -> Image:
        if len(value) > MAX_FILE_BYTES:
            raise RestoreAdmissionError("Restore file exceeds the supported 256 MiB bound")
        name = f"{hashlib.sha256(path.encode()).hexdigest()}.{side}.enc"
        image = Image(name=name, sha256=hashlib.sha256(value).hexdigest(), size=len(value))
        encoded = self.cipher.encrypt_bytes(
            value, context=f"restore:v2:{operation_id}:object:{name}"
        ).encode("ascii")
        atomic_write_exclusive(self._object_path(operation_id, image), encoded)
        self._read_image(operation_id, image)
        return image

    def _read_bounded(self, path: Path) -> bytes:
        digest, size = hash_file(path)
        with path.open("rb") as stream:
            value = stream.read(MAX_FILE_BYTES + 1)
        if len(value) != size or hashlib.sha256(value).hexdigest() != digest:
            raise RestoreAdmissionError("Restore bytes changed while preparing recovery")
        return value

    def _private_database(
        self, operation_id: str, value: bytes, source: Intent, applied_plan: RestorePlan
    ) -> bytes:
        """Only this newly owned scratch database receives SQLite bookkeeping writes."""
        from sqlalchemy import create_engine
        from sqlalchemy.engine import URL
        from sqlalchemy.orm import Session

        from job_apply_pro.storage.operations_repository import OperationsRepository

        path = checked_path(
            self.gate.operation_path(operation_id) / "bookkeeping.private.db", root=self.gate.root
        )
        atomic_write_exclusive(path, value)
        engine = create_engine(URL.create("sqlite", database=str(path)))
        try:
            with Session(engine) as session:
                OperationsRepository(session).save_restore_result(source.manifest, applied_plan)
        finally:
            engine.dispose()
        assert_restore_source_closed(path)
        result = self._read_bounded(path)
        # This is our own disposable scratch copy, never a prior recovery object.
        path.unlink()
        sync_directory(path.parent)
        return result

    def apply(self, source: Intent) -> RestorePlan:
        root = self.gate.root
        if not owns_restore(root):
            raise RestoreAdmissionError("Offline restore requires exclusive workspace ownership")
        self.gate.assert_clear()
        if source.workspace != str(root):
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        database = checked_path(root / safe_relative(source.database), root=root)
        assert_restore_source_closed(database)
        from job_apply_pro.services.backup import BackupService

        if BackupCategory.DATABASE in source.plan.categories:
            BackupService._require_resolved_media_cleanup(database)
            staged_database = checked_path(
                root / safe_relative(source.staged) / "database" / "job_apply_pro.db", root=root
            )
            assert_restore_source_closed(staged_database)
            BackupService._require_preserved_mail_attempts(database, staged_database)
        checked = self.host.prepare(
            source.plan,
            source.manifest,
            database=database,
            documents=root / safe_relative(source.documents),
            staging=(root / safe_relative(source.staged)).parent,
            backups=Path(source.manifest.archive_path).parent,
        )
        if checked != source:
            raise RestoreAdmissionError("Restore intent changed after review")
        # Recheck every staged input before making any operation visible to admission.
        input_bytes: dict[str, bytes] = {}
        input_total = 0
        for item in source.inputs:
            value = self._read_bounded(
                root / safe_relative(source.staged) / safe_relative(item.path)
            )
            if len(value) != item.size or hashlib.sha256(value).hexdigest() != item.sha256:
                raise RestoreAdmissionError("Staged restore bytes changed after review")
            input_total += len(value)
            if input_total > MAX_RESTORE_BYTES:
                raise RestoreAdmissionError("Restore postimages exceed the supported 1 GiB bound")
            input_bytes[item.path] = value
        operation_id = self.gate.allocate_operation()
        (self.gate.operation_path(operation_id) / "objects").mkdir()
        applied_plan = source.plan.model_copy(
            update={"status": RestoreStatus.APPLIED, "applied_at": datetime.now(UTC)}
        )
        # Always retain the closed original DB, including for document-only restore.
        original_database = self._read_bounded(database)
        before_total = len(original_database)
        targets: list[Replacement] = []
        database_before = self._save_image(
            operation_id, source.database, "before", original_database
        )
        for item in source.inputs:
            if item.path == "database/job_apply_pro.db":
                continue
            destination = self.host._destination(source, item)
            relative = destination.relative_to(root).as_posix()
            before = None
            if destination.exists():
                value = self._read_bounded(destination)
                before_total += len(value)
                if before_total > MAX_RESTORE_BYTES:
                    raise RestoreAdmissionError(
                        "Restore preimages exceed the supported 1 GiB bound"
                    )
                before = self._save_image(operation_id, relative, "before", value)
            after = self._save_image(operation_id, relative, "after", input_bytes[item.path])
            targets.append(Replacement(path=relative, before=before, after=after))
        after_database = self._private_database(
            operation_id,
            input_bytes.get("database/job_apply_pro.db", original_database),
            source,
            applied_plan,
        )
        if sum(target.after.size for target in targets) + len(after_database) > MAX_RESTORE_BYTES:
            raise RestoreAdmissionError("Restore postimages exceed the supported 1 GiB bound")
        targets.append(
            Replacement(
                path=source.database,
                before=database_before,
                after=self._save_image(operation_id, source.database, "after", after_database),
            )
        )
        prepared = PreparedRestore(
            operation_id=operation_id,
            workspace=str(root),
            source=source,
            applied_plan=applied_plan,
            targets=targets,
        )
        self._validate(prepared)
        self._preflight(prepared, expected="BEFORE")
        self.gate.write_v2_record(
            operation_id, "intent", prepared.model_dump(mode="json"), self.cipher
        )
        self.gate.activate_prepared(operation_id)
        for target in prepared.targets:
            self._install(prepared, target, target.after)
        self._write_receipt(prepared, "APPLIED")
        self.finalize(operation_id)
        return prepared.applied_plan

    def _validate(self, prepared: PreparedRestore) -> None:
        if (
            str(UUID(prepared.operation_id)) != prepared.operation_id
            or prepared.workspace != str(self.gate.root)
            or prepared.source.workspace != prepared.workspace
            or prepared.applied_plan.status is not RestoreStatus.APPLIED
            or prepared.applied_plan.model_dump(exclude={"status", "applied_at"})
            != prepared.source.plan.model_dump(exclude={"status", "applied_at"})
        ):
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        source = prepared.source
        root = self.gate.root
        database = checked_path(root / safe_relative(source.database), root=root)
        documents = checked_path(root / safe_relative(source.documents), root=root)
        staging = checked_path(root / safe_relative(source.staged), root=root)
        backups = checked_path(Path(source.manifest.archive_path).parent, root=root)
        directories = (documents, staging.parent, backups, self.gate.control)
        if (
            database.parent != root
            or staging.name != source.plan.id
            or source.plan.status is not RestoreStatus.STAGED
            or source.manifest.id != source.plan.backup_id
            or not source.plan.categories
            or not source.plan.categories.issubset(source.manifest.categories)
            or source.plan.file_count != len(source.inputs)
            or any(
                left == right or left in right.parents or right in left.parents
                for index, left in enumerate(directories)
                for right in directories[index + 1 :]
            )
            or any(
                directory == database or directory in database.parents for directory in directories
            )
            or len({item.path.casefold() for item in source.inputs}) != len(source.inputs)
            or sum(item.size for item in source.inputs) > MAX_RESTORE_BYTES
        ):
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        database_inputs = 0
        expected_documents: dict[str, tuple[str, int]] = {}
        for item in source.inputs:
            relative = safe_relative(item.path)
            if item.path == "database/job_apply_pro.db":
                database_inputs += 1
            elif (
                BackupCategory.DOCUMENTS in source.plan.categories
                and len(relative.parts) >= 2
                and relative.parts[0] == "documents"
            ):
                destination = self.host._destination(source, item).relative_to(root).as_posix()
                expected_documents[destination] = item.sha256, item.size
            else:
                raise RestoreAdmissionError(RECOVERY_MESSAGE)
        if database_inputs != int(BackupCategory.DATABASE in source.plan.categories):
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        expected = [
            self.host._destination(prepared.source, item).relative_to(self.gate.root).as_posix()
            for item in prepared.source.inputs
            if item.path != "database/job_apply_pro.db"
        ] + [prepared.source.database]
        if [item.path for item in prepared.targets] != expected or len(
            {path.casefold() for path in expected}
        ) != len(expected):
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        if prepared.targets[-1].before is None:
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        for target in prepared.targets[:-1]:
            if expected_documents.get(target.path) != (target.after.sha256, target.after.size):
                raise RestoreAdmissionError(RECOVERY_MESSAGE)
        for side in ("before", "after"):
            total = 0
            for target in prepared.targets:
                checked_path(self.gate.root / safe_relative(target.path), root=self.gate.root)
                value = target.before if side == "before" else target.after
                if value is None:
                    continue
                expected_name = f"{hashlib.sha256(target.path.encode()).hexdigest()}.{side}.enc"
                if value.name != expected_name:
                    raise RestoreAdmissionError(RECOVERY_MESSAGE)
                total += value.size
            if total > MAX_RESTORE_BYTES:
                raise RestoreAdmissionError(
                    "Restore images exceed the supported 1 GiB per side bound"
                )

    def _load(self, operation_id: str) -> PreparedRestore:
        prepared = PreparedRestore.model_validate(
            self.gate.read_v2_record(operation_id, "intent", self.cipher)
        )
        if prepared.operation_id != operation_id:
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        self._validate(prepared)
        return prepared

    @staticmethod
    def _review_fingerprint(prepared: PreparedRestore) -> str:
        return hashlib.sha256(f"{POLICY}:ROLLBACK:{digest_model(prepared)}".encode()).hexdigest()

    def _active(self, operation_id: str) -> None:
        if not self.gate.blocked() or self.gate.active_id() != operation_id:
            raise RestoreAdmissionError(
                "Only the still-blocked original operation can be recovered"
            )

    def _state(self, prepared: PreparedRestore, target: Replacement) -> Literal["BEFORE", "AFTER"]:
        path = checked_path(self.gate.root / safe_relative(target.path), root=self.gate.root)
        if target.path == prepared.source.database:
            assert_no_sqlite_sidecars(path)
        try:
            path.lstat()
        except FileNotFoundError:
            if target.before is None:
                return "BEFORE"
            raise RestoreAdmissionError(RECOVERY_MESSAGE) from None
        actual = hash_file(path)
        if target.before is not None and actual == (target.before.sha256, target.before.size):
            return "BEFORE"
        if actual == (target.after.sha256, target.after.size):
            return "AFTER"
        raise RestoreAdmissionError(
            "A restore target has unknown bytes; preserve it for manual recovery"
        )

    def _preflight(self, prepared: PreparedRestore, *, expected: str | None = None) -> None:
        # Verify ALL retained inputs and ALL live targets before the first recovery write.
        for target in prepared.targets:
            for image in (target.before, target.after):
                if image is not None:
                    self._read_image(prepared.operation_id, image)
            state = self._state(prepared, target)
            # Identical before/after images are always classified BEFORE.
            if (
                expected is not None
                and state != expected
                and not (
                    expected == "AFTER"
                    and target.before is not None
                    and (target.before.sha256, target.before.size)
                    == (target.after.sha256, target.after.size)
                )
            ):
                raise RestoreAdmissionError(RECOVERY_MESSAGE)

    def _install(self, prepared: PreparedRestore, target: Replacement, image: Image) -> None:
        path = checked_path(self.gate.root / safe_relative(target.path), root=self.gate.root)
        self._state(prepared, target)
        data = self._read_image(prepared.operation_id, image)
        path.parent.mkdir(parents=True, exist_ok=True)
        checked_path(path, root=self.gate.root)
        temporary = path.with_name(f".{path.name}.{prepared.operation_id}.{uuid4()}.restore.tmp")
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        self._state(prepared, target)
        temporary.replace(path)
        sync_directory(path.parent)

    def _decision(self, prepared: PreparedRestore) -> RollbackDecision | None:
        if not self.gate.has_v2_record(prepared.operation_id, "decision"):
            return None
        decision = RollbackDecision.model_validate(
            self.gate.read_v2_record(prepared.operation_id, "decision", self.cipher)
        )
        if decision.intent_sha256 != digest_model(
            prepared
        ) or decision.review_fingerprint != self._review_fingerprint(prepared):
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        return decision

    def _receipt(self, prepared: PreparedRestore) -> TerminalReceipt | None:
        if not self.gate.has_v2_record(prepared.operation_id, "receipt"):
            return None
        receipt = TerminalReceipt.model_validate(
            self.gate.read_v2_record(prepared.operation_id, "receipt", self.cipher)
        )
        expected = self._terminal(prepared, receipt.outcome)
        if receipt != expected:
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        decision = self._decision(prepared)
        if (receipt.outcome == "ROLLED_BACK") != (decision is not None):
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        return receipt

    @staticmethod
    def _terminal(
        prepared: PreparedRestore, outcome: Literal["APPLIED", "ROLLED_BACK"]
    ) -> TerminalReceipt:
        targets: list[tuple[str, str | None, int | None]] = []
        for target in prepared.targets:
            image = target.after if outcome == "APPLIED" else target.before
            targets.append(
                (target.path, image.sha256 if image else None, image.size if image else None)
            )
        return TerminalReceipt(
            intent_sha256=digest_model(prepared), outcome=outcome, targets=targets
        )

    def _write_receipt(
        self, prepared: PreparedRestore, outcome: Literal["APPLIED", "ROLLED_BACK"]
    ) -> None:
        if (outcome == "ROLLED_BACK") != (self._decision(prepared) is not None):
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        self._preflight(prepared, expected="AFTER" if outcome == "APPLIED" else "BEFORE")
        self.gate.write_v2_record(
            prepared.operation_id,
            "receipt",
            self._terminal(prepared, outcome).model_dump(mode="json"),
            self.cipher,
        )

    def finalize(self, operation_id: str) -> None:
        with workspace_access(self.gate.root, restore=True):
            self._active(operation_id)
            prepared = self._load(operation_id)
            receipt = self._receipt(prepared)
            if receipt is None:
                raise RestoreAdmissionError(RECOVERY_MESSAGE)
            self._preflight(
                prepared, expected="AFTER" if receipt.outcome == "APPLIED" else "BEFORE"
            )
            self.gate.finish_verified(operation_id)

    def rollback(self, operation_id: str, review_fingerprint: str) -> None:
        with workspace_access(self.gate.root, restore=True):
            self._active(operation_id)
            prepared = self._load(operation_id)
            if review_fingerprint != self._review_fingerprint(prepared):
                raise RestoreAdmissionError(
                    "Rollback review changed; inspect the original operation"
                )
            receipt = self._receipt(prepared)
            if receipt is not None:
                if receipt.outcome == "APPLIED":
                    raise RestoreAdmissionError(
                        "Restore is already applied; only verified finalization is supported"
                    )
                self.finalize(operation_id)
                return
            self._preflight(prepared)
            if self._decision(prepared) is None:
                decision = RollbackDecision(
                    intent_sha256=digest_model(prepared), review_fingerprint=review_fingerprint
                )
                self.gate.write_v2_record(
                    operation_id, "decision", decision.model_dump(mode="json"), self.cipher
                )
            # The sealed inventory always puts the database last. No live SQLite reads.
            for target in prepared.targets:
                if self._state(prepared, target) == "BEFORE":
                    continue
                if target.before is not None:
                    self._install(prepared, target, target.before)
                else:
                    # Its exact after-image is retained, authenticated and encrypted.
                    # Only a file introduced by this operation may be removed.
                    path = checked_path(
                        self.gate.root / safe_relative(target.path), root=self.gate.root
                    )
                    path.unlink()
                    sync_directory(path.parent)
            self._write_receipt(prepared, "ROLLED_BACK")
            self.finalize(operation_id)

    def inspect(self, operation_id: str) -> dict[str, object]:
        with workspace_access(self.gate.root, restore=True):
            prepared = self._load(operation_id)
            receipt = self._receipt(prepared)
            if not self.gate.blocked():
                if receipt is None:
                    raise RestoreAdmissionError(RECOVERY_MESSAGE)
                return {
                    "operation_id": operation_id,
                    "version": 2,
                    "state": receipt.outcome,
                    "rollback_supported": False,
                    "review_fingerprint": None,
                }
            self._active(operation_id)
            self._preflight(prepared)
            decision = self._decision(prepared)
            return {
                "operation_id": operation_id,
                "version": 2,
                "state": receipt.outcome
                if receipt
                else "ROLLING_BACK"
                if decision
                else "INTERRUPTED",
                "rollback_supported": receipt is None,
                "review_fingerprint": self._review_fingerprint(prepared)
                if receipt is None
                else None,
            }
