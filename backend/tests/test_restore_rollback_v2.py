"""Adversarial interrupted-operation recovery, without live providers or power-loss claims."""

import copy
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from job_apply_pro.domain.operations import BackupCategory, RestoreCreate
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.backup import BackupService
from job_apply_pro.services.restore_recovery import (
    Receipt,
    RestoreRecoveryService,
    Target,
    _intent_hash,
    hash_file,
)
from job_apply_pro.services.restore_rollback import (
    Image,
    PreparedRestore,
    Replacement,
    RestoreRollback,
    RollbackDecision,
    digest_model,
)
from job_apply_pro.storage.operations_repository import OperationsRepository
from job_apply_pro.storage.restore_gate_repository import (
    RestoreAdmissionError,
    RestoreGateRepository,
    workspace_access,
)
from test_restore_admission import KEY, Workspace, cli, environment, run
from test_restore_admission import workspace as workspace


class Interrupted(RuntimeError):  # noqa: N818 - deliberate test-only crash boundary
    pass


@pytest.fixture
def changed_workspace(workspace: Workspace) -> Workspace:
    (workspace.root / "documents" / "letter.enc").write_bytes(b"current-letter")
    return workspace


def _live(workspace: Workspace) -> dict[str, bytes | None]:
    return {
        name: (workspace.root / name).read_bytes() if (workspace.root / name).exists() else None
        for name in (
            "app.db",
            "documents/letter.enc",
            "documents/resume.enc",
            "documents/unrelated.enc",
        )
    }


def _host(workspace: Workspace) -> RestoreRecoveryService:
    return RestoreRecoveryService(workspace.root, workspace.cipher)


def _interrupted_apply(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, *, after_installs: int = 0
) -> tuple[RestoreRollback, PreparedRestore]:
    original_install = RestoreRollback._install
    original_activate = RestoreGateRepository.activate_prepared
    installed = 0

    def install(
        self: RestoreRollback, prepared: PreparedRestore, target: Replacement, image: Image
    ) -> None:
        nonlocal installed
        original_install(self, prepared, target, image)
        installed += 1
        if installed == after_installs:
            raise Interrupted("after target install")

    def activate(self: RestoreGateRepository, operation_id: str) -> None:
        original_activate(self, operation_id)
        if after_installs == 0:
            raise Interrupted("after guard publication")

    with monkeypatch.context() as patch:
        patch.setattr(RestoreRollback, "_install", install)
        patch.setattr(RestoreGateRepository, "activate_prepared", activate)
        with workspace_access(workspace.root, restore=True), pytest.raises(Interrupted):
            _host(workspace).apply(workspace.prepare())
    operation_id = workspace.gate.active_id()
    recovery = RestoreRollback(_host(workspace))
    return recovery, recovery._load(operation_id)


def _rollback(recovery: RestoreRollback, prepared: PreparedRestore) -> None:
    recovery.host.rollback(prepared.operation_id, recovery._review_fingerprint(prepared))


def _packaged_restore_verifier(*, reveal_failure: bool = False) -> str:
    source = (Path(__file__).parents[2] / "scripts" / "test_packaged_backend.ps1").read_text(
        encoding="utf-8"
    )
    verifier = source.split("$restoreEvidenceScript = @'", 1)[1].split("\n'@", 1)[0]
    if reveal_failure:
        hidden = (
            "    except Exception:\n"
            '        print("Packaged durable restore evidence verification failed.", '
            "file=sys.stderr)"
        )
        revealed = "    except Exception as error:\n        print(str(error), file=sys.stderr)"
        assert hidden in verifier
        verifier = verifier.replace(hidden, revealed)
    return verifier


def _verify_packaged_restore(
    workspace: Workspace,
    operation_id: str,
    database_before: tuple[str, int],
    document_before: tuple[str, int],
    *,
    reveal_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-",
            str(workspace.root),
            operation_id,
            database_before[0],
            str(database_before[1]),
            workspace.plan.id,
            "documents/letter.enc",
            document_before[0],
            str(document_before[1]),
        ],
        input=_packaged_restore_verifier(reveal_failure=reveal_failure),
        env={**environment(workspace.root), "JAP_MASTER_KEY": KEY},
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _rewrite_restore_records(
    workspace: Workspace,
    operation_id: str,
    intent: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    canonical = copy.deepcopy(intent)
    canonical["source"]["plan"]["categories"] = sorted(canonical["source"]["plan"]["categories"])
    canonical["source"]["manifest"]["categories"] = sorted(
        canonical["source"]["manifest"]["categories"]
    )
    canonical["applied_plan"]["categories"] = sorted(canonical["applied_plan"]["categories"])
    receipt["intent_sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    operation = workspace.gate.operation_path(operation_id)
    (operation / "intent.v2.enc").write_text(
        workspace.cipher.encrypt_json(intent, context=f"restore:v2:{operation_id}:intent"),
        encoding="ascii",
    )
    (operation / "receipt.v2.enc").write_text(
        workspace.cipher.encrypt_json(receipt, context=f"restore:v2:{operation_id}:receipt"),
        encoding="ascii",
    )


def _terminal_restore_records(
    workspace: Workspace, operation_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        cast(
            dict[str, Any],
            workspace.gate.read_v2_record(operation_id, "intent", workspace.cipher),
        ),
        cast(
            dict[str, Any],
            workspace.gate.read_v2_record(operation_id, "receipt", workspace.cipher),
        ),
    )


@pytest.mark.parametrize("after_installs", [0, 1, 2, 3])
def test_rollback_restores_exact_original_database_and_documents_at_each_install_boundary(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch, after_installs: int
) -> None:
    before = _live(changed_workspace)
    recovery, prepared = _interrupted_apply(
        changed_workspace, monkeypatch, after_installs=after_installs
    )
    assert prepared.targets[-1].path == "app.db"
    assert prepared.targets[-1].before is not None
    assert recovery.inspect(prepared.operation_id)["rollback_supported"] is True

    _rollback(recovery, prepared)

    assert _live(changed_workspace) == before
    assert not changed_workspace.gate.blocked()
    assert recovery.inspect(prepared.operation_id) == {
        "operation_id": prepared.operation_id,
        "version": 2,
        "state": "ROLLED_BACK",
        "rollback_supported": False,
        "review_fingerprint": None,
    }
    assert recovery._receipt(prepared).outcome == "ROLLED_BACK"  # type: ignore[union-attr]


def test_document_only_restore_also_retains_database_before_bookkeeping(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    engine = create_engine(f"sqlite:///{workspace.database.as_posix()}")
    try:
        with Session(engine) as session:
            service = BackupService(
                OperationsRepository(session),
                workspace.cipher,
                database_url=f"sqlite:///{workspace.database.as_posix()}",
                document_dir=workspace.root / "documents",
                backup_dir=workspace.root / "backups",
                staging_dir=workspace.root / "restore-staging",
            )
            plan = service.stage_restore(
                workspace.manifest.id, RestoreCreate(categories={BackupCategory.DOCUMENTS})
            )
    finally:
        engine.dispose()
    documents_only = Workspace(workspace.root, plan, workspace.manifest, workspace.cipher)
    before = _live(documents_only)
    recovery, prepared = _interrupted_apply(documents_only, monkeypatch, after_installs=3)
    assert not list(workspace.root.rglob("bookkeeping.private.db"))
    database = prepared.targets[-1]
    assert database.path == "app.db"
    assert database.before is not None
    assert recovery._read_image(prepared.operation_id, database.before) == before["app.db"]
    assert _live(documents_only)["app.db"] != before["app.db"]

    _rollback(recovery, prepared)

    assert _live(documents_only) == before


@pytest.mark.parametrize("corrupt_side", ["before", "after"])
def test_every_image_is_authenticated_before_guard_and_first_target_write(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch, corrupt_side: str
) -> None:
    workspace = changed_workspace
    before = _live(workspace)
    original = RestoreRollback._save_image
    corrupted = False

    def corrupt(
        self: RestoreRollback, operation_id: str, path: str, side: str, value: bytes
    ) -> Image:
        nonlocal corrupted
        image = original(self, operation_id, path, side, value)
        if side == corrupt_side and not corrupted:
            self._object_path(operation_id, image).write_bytes(b"corrupted-retained-image")
            corrupted = True
        return image

    with monkeypatch.context() as patch:
        patch.setattr(RestoreRollback, "_save_image", corrupt)
        with (
            workspace_access(workspace.root, restore=True),
            pytest.raises((RestoreAdmissionError, ValueError)),
        ):
            _host(workspace).apply(workspace.prepare())

    assert corrupted
    assert not workspace.gate.blocked()
    assert _live(workspace) == before


def test_private_bookkeeping_failure_leaves_original_files_and_admission_untouched(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    before = _live(workspace)

    def fail(*args: object, **kwargs: object) -> bytes:
        del args, kwargs
        raise Interrupted("private bookkeeping failed")

    monkeypatch.setattr(RestoreRollback, "_private_database", fail)
    with workspace_access(workspace.root, restore=True), pytest.raises(Interrupted):
        _host(workspace).apply(workspace.prepare())

    assert not workspace.gate.blocked()
    assert _live(workspace) == before


def test_pre_guard_preparation_failure_discards_only_its_new_operation(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    before = _live(workspace)
    original = RestoreRollback._save_image
    saved = 0

    def stop_after_first_image(
        self: RestoreRollback, operation_id: str, path: str, side: str, value: bytes
    ) -> Image:
        nonlocal saved
        result = original(self, operation_id, path, side, value)
        saved += 1
        if saved == 1:
            raise Interrupted("pre-guard image interruption")
        return result

    monkeypatch.setattr(RestoreRollback, "_save_image", stop_after_first_image)
    with workspace_access(workspace.root, restore=True), pytest.raises(Interrupted):
        _host(workspace).apply(workspace.prepare())

    operations = workspace.gate.control / "operations"
    assert saved == 1
    assert not workspace.gate.blocked()
    assert not operations.exists() or not list(operations.iterdir())
    assert _live(workspace) == before


def test_staged_documents_are_read_and_sealed_sequentially_after_operation_allocation(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    staged = Path(workspace.plan.staged_path)
    events: list[str] = []
    original_read = RestoreRollback._read_bounded
    original_read_image = RestoreRollback._read_image
    original_save = RestoreRollback._save_image
    original_allocate = RestoreGateRepository.allocate_operation

    def allocate(self: RestoreGateRepository) -> str:
        result = original_allocate(self)
        events.append("allocate")
        return result

    def read(self: RestoreRollback, path: Path) -> bytes:
        result = original_read(self, path)
        if path.is_relative_to(staged) and path.relative_to(staged).parts[0] == "documents":
            events.append(f"read:{path.name}")
        return result

    def save(self: RestoreRollback, operation_id: str, path: str, side: str, value: bytes) -> Image:
        result = original_save(self, operation_id, path, side, value)
        if side == "after" and path.startswith("documents/"):
            events.append(f"seal:{Path(path).name}")
        return result

    def authenticate(self: RestoreRollback, operation_id: str, image: Image) -> bytes:
        events.append("authenticate")
        return original_read_image(self, operation_id, image)

    monkeypatch.setattr(RestoreGateRepository, "allocate_operation", allocate)
    monkeypatch.setattr(RestoreRollback, "_read_bounded", read)
    monkeypatch.setattr(RestoreRollback, "_save_image", save)
    monkeypatch.setattr(RestoreRollback, "_read_image", authenticate)
    with workspace_access(workspace.root, restore=True):
        _host(workspace).apply(workspace.prepare())

    assert events[0] == "allocate"
    assert events[1:5] == [
        "read:letter.enc",
        "seal:letter.enc",
        "read:resume.enc",
        "seal:resume.enc",
    ]
    assert events[5:] and set(events[5:]) == {"authenticate"}


def test_release_verifier_authenticates_exact_terminal_inventory_and_rejects_extra_evidence(
    changed_workspace: Workspace,
) -> None:
    workspace = changed_workspace
    database_before = hash_file(workspace.database)
    document_before = hash_file(workspace.root / "documents" / "letter.enc")
    with workspace_access(workspace.root, restore=True):
        _host(workspace).apply(workspace.prepare())
    operations = list((workspace.gate.control / "operations").iterdir())
    assert len(operations) == 1
    operation_id = operations[0].name

    accepted = _verify_packaged_restore(workspace, operation_id, database_before, document_before)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    unexpected = operations[0] / "bookkeeping.private.db"
    unexpected.write_bytes(b"plaintext scratch must never be accepted")
    refused = _verify_packaged_restore(workspace, operation_id, database_before, document_before)
    assert refused.returncode == 1
    assert refused.stderr.strip() == "Packaged durable restore evidence verification failed."


def _completed_packaged_evidence(
    workspace: Workspace,
) -> tuple[str, tuple[str, int], tuple[str, int], dict[str, Any], dict[str, Any]]:
    database_before = hash_file(workspace.database)
    document_before = hash_file(workspace.root / "documents" / "letter.enc")
    with workspace_access(workspace.root, restore=True):
        _host(workspace).apply(workspace.prepare())
    operations = list((workspace.gate.control / "operations").iterdir())
    assert len(operations) == 1
    operation_id = operations[0].name
    intent, receipt = _terminal_restore_records(workspace, operation_id)
    return operation_id, database_before, document_before, intent, receipt


@pytest.mark.parametrize(
    ("malformation", "message"),
    [
        ("source-version", "Restore source no longer matches its reviewed manifest"),
        ("manifest-binding", "Restore source no longer matches its reviewed manifest"),
        ("file-count", "Invalid restore source inventory"),
        ("database-cardinality", "Restore database input does not match its reviewed category"),
        ("case-collision", "Restore source contains case-colliding inputs"),
        ("source-total", "Restore source exceeds the supported 1 GiB bound"),
    ],
)
def test_release_verifier_rechecks_runtime_source_invariants(
    changed_workspace: Workspace, malformation: str, message: str
) -> None:
    workspace = changed_workspace
    operation_id, database_before, document_before, intent, receipt = _completed_packaged_evidence(
        workspace
    )
    source = intent["source"]
    source_plan = source["plan"]
    applied_plan = intent["applied_plan"]
    inputs = source["inputs"]
    if malformation == "source-version":
        source["version"] = 2
    elif malformation == "manifest-binding":
        replacement = str(uuid4())
        source_plan["backup_id"] = replacement
        applied_plan["backup_id"] = replacement
    elif malformation == "file-count":
        source_plan["file_count"] += 1
        applied_plan["file_count"] += 1
    elif malformation == "database-cardinality":
        source_plan["categories"] = ["DOCUMENTS"]
        applied_plan["categories"] = ["DOCUMENTS"]
    else:
        database_input = next(
            item for item in inputs if item["path"] == "database/job_apply_pro.db"
        )
        if malformation == "case-collision":
            inputs.append(copy.deepcopy(database_input))
        else:
            for _ in range(4):
                duplicate = copy.deepcopy(database_input)
                duplicate["size"] = 256 * 1024 * 1024
                inputs.append(duplicate)
        source_plan["file_count"] = len(inputs)
        applied_plan["file_count"] = len(inputs)
    _rewrite_restore_records(workspace, operation_id, intent, receipt)

    refused = _verify_packaged_restore(
        workspace,
        operation_id,
        database_before,
        document_before,
        reveal_failure=True,
    )
    assert refused.returncode == 1
    assert refused.stderr.strip() == message


@pytest.mark.parametrize("side", ["before", "after"])
def test_release_verifier_enforces_one_gibibyte_bound_for_each_image_side(
    changed_workspace: Workspace, side: str
) -> None:
    workspace = changed_workspace
    operation_id, database_before, document_before, intent, receipt = _completed_packaged_evidence(
        workspace
    )
    source = intent["source"]
    inputs = source["inputs"]
    targets = intent["targets"]
    receipt_targets = receipt["targets"]
    empty_hash = hashlib.sha256(b"").hexdigest()
    extra_targets = []
    extra_receipts = []
    for index in range(5):
        path = f"documents/aggregate-{index}.enc"
        (workspace.root / path).write_bytes(b"")
        inputs.append({"path": path, "sha256": empty_hash, "size": 0})
        after_size = 256 * 1024 * 1024 if side == "after" else 0
        before = None
        if side == "before":
            before = {
                "name": f"{hashlib.sha256(path.encode()).hexdigest()}.before.enc",
                "sha256": "0" * 64,
                "size": 256 * 1024 * 1024,
            }
        after = {
            "name": f"{hashlib.sha256(path.encode()).hexdigest()}.after.enc",
            "sha256": empty_hash if after_size == 0 else "0" * 64,
            "size": after_size,
        }
        extra_targets.append({"path": path, "before": before, "after": after})
        extra_receipts.append([path, after["sha256"], after["size"]])
    targets[-1:-1] = extra_targets
    receipt_targets[-1:-1] = extra_receipts
    source["plan"]["file_count"] = len(inputs)
    intent["applied_plan"]["file_count"] = len(inputs)
    _rewrite_restore_records(workspace, operation_id, intent, receipt)

    refused = _verify_packaged_restore(
        workspace,
        operation_id,
        database_before,
        document_before,
        reveal_failure=True,
    )
    assert refused.returncode == 1
    assert refused.stderr.strip() == "Restore images exceed the supported 1 GiB per side bound"


@pytest.mark.parametrize(
    ("location", "message"),
    [
        ("source", "Invalid restore source input"),
        ("image", "Invalid restore image"),
        ("receipt", "Invalid restore receipt inventory"),
    ],
)
def test_release_verifier_rejects_boolean_byte_counts(
    changed_workspace: Workspace, location: str, message: str
) -> None:
    workspace = changed_workspace
    operation_id, database_before, document_before, intent, receipt = _completed_packaged_evidence(
        workspace
    )
    path = "documents/letter.enc"
    value = b"x"
    digest = hashlib.sha256(value).hexdigest()
    source_input = next(item for item in intent["source"]["inputs"] if item["path"] == path)
    target = next(item for item in intent["targets"] if item["path"] == path)
    receipt_target = next(item for item in receipt["targets"] if item[0] == path)
    source_input["sha256"] = digest
    source_input["size"] = True if location == "source" else 1
    target["after"]["sha256"] = digest
    target["after"]["size"] = True if location == "image" else 1
    receipt_target[1] = digest
    receipt_target[2] = True if location == "receipt" else 1
    (workspace.root / path).write_bytes(value)
    image_name = target["after"]["name"]
    (workspace.gate.operation_path(operation_id) / "objects" / image_name).write_text(
        workspace.cipher.encrypt_bytes(
            value, context=f"restore:v2:{operation_id}:object:{image_name}"
        ),
        encoding="ascii",
    )
    _rewrite_restore_records(workspace, operation_id, intent, receipt)

    refused = _verify_packaged_restore(
        workspace,
        operation_id,
        database_before,
        document_before,
        reveal_failure=True,
    )
    assert refused.returncode == 1
    assert refused.stderr.strip() == message


def test_rollback_removes_only_known_introduced_target_and_preserves_unrelated_files(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    introduced = workspace.root / "documents" / "letter.enc"
    introduced.unlink()
    before = _live(workspace)
    recovery, prepared = _interrupted_apply(workspace, monkeypatch, after_installs=3)
    assert prepared.targets[0].before is None
    assert introduced.read_bytes() == b"reviewed-letter"

    _rollback(recovery, prepared)

    assert not introduced.exists()
    assert _live(workspace) == before


@pytest.mark.parametrize(
    "failure",
    [
        "unknown-database",
        "unknown-document",
        "missing-before",
        "corrupt-before",
        "missing-after",
        "wrong-key",
        "other-operation",
        "other-operation-object",
        "wal",
        "shm",
        "journal",
    ],
)
def test_all_uncertain_targets_or_recovery_evidence_block_before_any_rollback_write(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    workspace = changed_workspace
    recovery, prepared = _interrupted_apply(workspace, monkeypatch, after_installs=3)
    database = prepared.targets[-1]
    assert database.before is not None
    if failure == "unknown-database":
        workspace.database.write_bytes(b"unknown third database bytes")
    elif failure == "unknown-document":
        (workspace.root / "documents" / "resume.enc").write_bytes(b"unknown third document bytes")
    elif failure in {"missing-before", "corrupt-before", "missing-after"}:
        image = database.after if failure == "missing-after" else database.before
        path = recovery._object_path(prepared.operation_id, image)
        if failure == "corrupt-before":
            path.write_bytes(b"corrupted database preimage")
        else:
            path.unlink()
    elif failure == "wrong-key":
        wrong_cipher = SensitiveDataCipher(StaticKeyProvider(b"w" * 32, key_id="local-v1"))
        recovery = RestoreRollback(RestoreRecoveryService(workspace.root, wrong_cipher))
    elif failure == "other-operation":
        workspace.gate.guard.write_text(str(uuid4()), encoding="ascii")
    elif failure == "other-operation-object":
        original_bytes = recovery._read_image(prepared.operation_id, database.before)
        swapped = workspace.cipher.encrypt_bytes(
            original_bytes, context=f"restore:v2:{uuid4()}:object:{database.before.name}"
        )
        recovery._object_path(prepared.operation_id, database.before).write_text(
            swapped, encoding="ascii"
        )
    else:
        workspace.database.with_name(f"app.db-{failure}").write_bytes(b"unknown sidecar")
    before = _live(workspace)
    installs: list[str] = []
    original = RestoreRollback._install

    def track(
        self: RestoreRollback, model: PreparedRestore, target: Replacement, image: Image
    ) -> None:
        installs.append(target.path)
        original(self, model, target, image)

    monkeypatch.setattr(RestoreRollback, "_install", track)
    with pytest.raises((RestoreAdmissionError, OSError, ValueError)):
        _rollback(recovery, prepared)

    assert installs == []
    assert _live(workspace) == before
    assert workspace.gate.blocked()
    assert not workspace.gate.has_v2_record(prepared.operation_id, "decision")
    assert not workspace.gate.has_v2_record(prepared.operation_id, "receipt")
    if failure in {"wal", "shm", "journal"}:
        assert workspace.database.with_name(f"app.db-{failure}").read_bytes() == b"unknown sidecar"


def test_unknown_introduced_file_is_not_deleted_and_no_other_target_is_rolled_back(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    introduced = workspace.root / "documents" / "letter.enc"
    introduced.unlink()
    recovery, prepared = _interrupted_apply(workspace, monkeypatch, after_installs=3)
    introduced.write_bytes(b"user replacement after interrupted restore")
    before = _live(workspace)

    with pytest.raises(RestoreAdmissionError, match="unknown bytes"):
        _rollback(recovery, prepared)

    assert _live(workspace) == before
    assert workspace.gate.blocked()


def test_mismatched_review_fingerprint_does_not_publish_decision_or_write_targets(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    recovery, prepared = _interrupted_apply(changed_workspace, monkeypatch, after_installs=3)
    before = _live(changed_workspace)

    with pytest.raises(RestoreAdmissionError, match="review changed"):
        recovery.host.rollback(prepared.operation_id, "0" * 64)

    assert _live(changed_workspace) == before
    assert not changed_workspace.gate.has_v2_record(prepared.operation_id, "decision")


def test_applied_receipt_allows_finalization_only_not_rollback(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace

    def stop(*args: object) -> None:
        raise Interrupted("after applied receipt")

    with monkeypatch.context() as patch:
        patch.setattr(RestoreRollback, "finalize", stop)
        with workspace_access(workspace.root, restore=True), pytest.raises(Interrupted):
            _host(workspace).apply(workspace.prepare())
    recovery = RestoreRollback(_host(workspace))
    prepared = recovery._load(workspace.gate.active_id())
    before = _live(workspace)
    assert recovery.inspect(prepared.operation_id)["rollback_supported"] is False

    with pytest.raises(RestoreAdmissionError, match="only verified finalization"):
        _rollback(recovery, prepared)
    assert _live(workspace) == before
    recovery.host.finalize(prepared.operation_id)
    assert not workspace.gate.blocked()


def test_authenticated_rollback_decision_blocks_forward_receipt_and_finalization(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    recovery, prepared = _interrupted_apply(workspace, monkeypatch, after_installs=3)
    decision = RollbackDecision(
        intent_sha256=digest_model(prepared),
        review_fingerprint=recovery._review_fingerprint(prepared),
    )
    with workspace_access(workspace.root, restore=True):
        workspace.gate.write_v2_record(
            prepared.operation_id, "decision", decision.model_dump(mode="json"), workspace.cipher
        )
        with pytest.raises(RestoreAdmissionError):
            recovery._write_receipt(prepared, "APPLIED")
        # Even a separately authenticated but contradictory terminal receipt is refused.
        workspace.gate.write_v2_record(
            prepared.operation_id,
            "receipt",
            recovery._terminal(prepared, "APPLIED").model_dump(mode="json"),
            workspace.cipher,
        )
    before = _live(workspace)

    with pytest.raises(RestoreAdmissionError):
        recovery.host.finalize(prepared.operation_id)

    assert _live(workspace) == before
    assert workspace.gate.blocked()


def test_repeated_interrupted_rollback_skips_completed_targets_and_keeps_database_last(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    original_bytes = _live(workspace)
    recovery, prepared = _interrupted_apply(workspace, monkeypatch, after_installs=3)
    original_install = RestoreRollback._install
    order: list[str] = []

    def stop(
        self: RestoreRollback, model: PreparedRestore, target: Replacement, image: Image
    ) -> None:
        original_install(self, model, target, image)
        order.append(target.path)
        raise Interrupted("rollback after one replacement")

    for expected_count in (1, 2, 3):
        with monkeypatch.context() as patch:
            patch.setattr(RestoreRollback, "_install", stop)
            with pytest.raises(Interrupted):
                _rollback(recovery, prepared)
        assert len(order) == expected_count
        assert workspace.gate.blocked()
        assert recovery.inspect(prepared.operation_id)["state"] == "ROLLING_BACK"

    assert order == [target.path for target in prepared.targets]
    assert order[-1] == "app.db"
    _rollback(recovery, prepared)
    assert _live(workspace) == original_bytes
    assert not workspace.gate.blocked()


def test_rollback_after_guard_clear_cannot_revert_later_local_history(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    recovery, prepared = _interrupted_apply(changed_workspace, monkeypatch, after_installs=3)
    _rollback(recovery, prepared)
    changed_workspace.database.write_bytes(b"later admitted history must never be overwritten")
    before = _live(changed_workspace)

    with pytest.raises(RestoreAdmissionError, match="still-blocked"):
        _rollback(recovery, prepared)

    assert _live(changed_workspace) == before


def test_interruption_after_removing_introduced_file_is_idempotently_recoverable(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    introduced = workspace.root / "documents" / "letter.enc"
    introduced.unlink()
    before = _live(workspace)
    recovery, prepared = _interrupted_apply(workspace, monkeypatch, after_installs=3)
    original = Path.unlink

    def stop(path: Path, missing_ok: bool = False) -> None:
        original(path, missing_ok=missing_ok)
        if path == introduced:
            raise Interrupted("after removing the introduced file")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", stop)
        with pytest.raises(Interrupted):
            _rollback(recovery, prepared)
    assert not introduced.exists()
    assert workspace.gate.blocked()
    assert recovery.inspect(prepared.operation_id)["state"] == "ROLLING_BACK"

    _rollback(recovery, prepared)

    assert _live(workspace) == before
    assert not workspace.gate.blocked()


@pytest.mark.parametrize("changed_target", ["database", "document"])
def test_live_target_change_before_guard_rejects_stale_rollback_baseline(
    changed_workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    changed_target: str,
) -> None:
    workspace = changed_workspace
    original_write = RestoreGateRepository.write_v2_record

    def change_database_after_intent(
        gate: RestoreGateRepository,
        operation_id: str,
        name: str,
        value: dict[str, object],
        cipher: SensitiveDataCipher,
    ) -> None:
        original_write(gate, operation_id, name, value, cipher)
        if name == "intent":
            target = (
                workspace.database
                if changed_target == "database"
                else workspace.root / "documents" / "letter.enc"
            )
            target.write_bytes(target.read_bytes() + b"external-change")

    monkeypatch.setattr(RestoreGateRepository, "write_v2_record", change_database_after_intent)
    with (
        workspace_access(workspace.root, restore=True),
        pytest.raises(RestoreAdmissionError, match="unknown bytes"),
    ):
        _host(workspace).apply(workspace.prepare())

    assert not workspace.gate.blocked()
    assert not list((workspace.gate.control / "operations").glob("*"))


def test_rollback_receipt_after_interruption_finalizes_without_repeating_target_writes(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    before = _live(workspace)
    recovery, prepared = _interrupted_apply(workspace, monkeypatch, after_installs=3)

    def stop(*args: object) -> None:
        raise Interrupted("after rollback receipt")

    with monkeypatch.context() as patch:
        patch.setattr(RestoreRollback, "finalize", stop)
        with pytest.raises(Interrupted):
            _rollback(recovery, prepared)
    assert workspace.gate.blocked()
    assert _live(workspace) == before
    assert recovery.inspect(prepared.operation_id)["state"] == "ROLLED_BACK"

    def forbidden(*args: object) -> None:
        raise AssertionError("A terminal rollback must not replace targets again")

    monkeypatch.setattr(RestoreRollback, "_install", forbidden)
    _rollback(recovery, prepared)
    assert not workspace.gate.blocked()
    assert _live(workspace) == before


def test_legacy_v1_operation_remains_authenticated_manual_or_completion_only(
    changed_workspace: Workspace,
) -> None:
    workspace = changed_workspace
    intent = workspace.prepare()
    with workspace_access(workspace.root, restore=True):
        operation_id = workspace.gate.begin(intent.model_dump(mode="json"), workspace.cipher)
    preimage = workspace.cipher.encrypt_bytes(
        workspace.database.read_bytes(), context=f"restore:v1:{operation_id}:database-preimage"
    )
    (workspace.gate.operation_path(operation_id) / "database-preimage.enc").write_text(
        preimage, encoding="ascii"
    )
    before = _live(workspace)
    host = _host(workspace)

    assert host.inspect(operation_id) == {
        "operation_id": operation_id,
        "version": 1,
        "state": "LEGACY_COMPLETION_OR_MANUAL_RECOVERY",
        "rollback_supported": False,
        "review_fingerprint": None,
    }
    with pytest.raises(RestoreAdmissionError, match="Legacy restore"):
        host.rollback(operation_id, "0" * 64)
    with pytest.raises(RestoreAdmissionError):
        host.finalize(operation_id)
    assert _live(workspace) == before
    assert workspace.gate.blocked()


def test_legacy_v1_authenticated_completion_still_finalizes_without_reintroducing_apply(
    changed_workspace: Workspace,
) -> None:
    workspace = changed_workspace
    host = _host(workspace)
    intent = workspace.prepare()
    with workspace_access(workspace.root, restore=True):
        operation_id = workspace.gate.begin(intent.model_dump(mode="json"), workspace.cipher)
        targets = []
        for source in intent.inputs:
            destination = host._destination(intent, source)
            # Construct a closed v1 terminal state entirely within this synthetic fixture.
            host._replace(
                Path(workspace.plan.staged_path) / source.path, destination, source, operation_id
            )
            digest, size = hash_file(destination)
            targets.append(
                Target(
                    path=destination.relative_to(workspace.root).as_posix(),
                    sha256=digest,
                    size=size,
                )
            )
        receipt = Receipt(intent_sha256=_intent_hash(intent), targets=targets)
        workspace.gate.write_record(
            operation_id, "receipt", receipt.model_dump(mode="json"), workspace.cipher
        )
    before_finalize = _live(workspace)

    host.finalize(operation_id)

    assert not workspace.gate.blocked()
    assert _live(workspace) == before_finalize
    assert (workspace.root / "documents" / "resume.enc").read_bytes() == b"reviewed-document"
    assert (workspace.root / "documents" / "unrelated.enc").read_bytes() == b"unrelated-document"


@pytest.mark.parametrize("side", ["before", "after"])
def test_aggregate_image_bounds_refuse_before_guard_without_changing_original_targets(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch, side: str
) -> None:
    import job_apply_pro.services.restore_rollback as module

    workspace = changed_workspace
    staged_total = sum(entry.size_bytes for entry in workspace.manifest.entries)
    if side == "before":
        (workspace.root / "documents" / "letter.enc").write_bytes(b"x" * 100_000)
        current_total = sum(len(value) for value in _live(workspace).values() if value is not None)
        assert current_total > staged_total
        maximum = (current_total + staged_total) // 2
    else:
        maximum = staged_total - 1
    monkeypatch.setattr(module, "MAX_RESTORE_BYTES", maximum)
    before = _live(workspace)

    with (
        workspace_access(workspace.root, restore=True),
        pytest.raises(RestoreAdmissionError, match=r"preimages|postimages"),
    ):
        _host(workspace).apply(workspace.prepare())

    assert not workspace.gate.blocked()
    assert _live(workspace) == before


@pytest.mark.parametrize("alias", ["target", "object-directory", "control-directory"])
def test_recovery_rejects_windows_reparse_aliases_before_any_target_write(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch, alias: str
) -> None:
    workspace = changed_workspace
    recovery, prepared = _interrupted_apply(workspace, monkeypatch, after_installs=3)
    marked = (
        workspace.root / "documents" / "resume.enc"
        if alias == "target"
        else workspace.gate.operation_path(prepared.operation_id) / "objects"
        if alias == "object-directory"
        else workspace.gate.control
    )
    original_lstat = Path.lstat

    def reparse(path: Path) -> os.stat_result:
        info = original_lstat(path)
        if path == marked:
            # Deterministic Windows reparse evidence, without requiring symlink privileges.
            return cast(
                os.stat_result,
                SimpleNamespace(
                    st_mode=info.st_mode,
                    st_file_attributes=getattr(info, "st_file_attributes", 0) | 0x400,
                ),
            )
        return info

    before = _live(workspace)
    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(RestoreAdmissionError):
        _rollback(recovery, prepared)

    assert _live(workspace) == before
    assert workspace.gate.blocked()


def test_recovery_rejects_hardlinked_retained_image_without_writing_live_targets(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    recovery, prepared = _interrupted_apply(workspace, monkeypatch, after_installs=3)
    image = prepared.targets[-1].before
    assert image is not None
    linked = workspace.root / "synthetic-preimage-hardlink.enc"
    linked.hardlink_to(recovery._object_path(prepared.operation_id, image))
    before = _live(workspace)

    with pytest.raises(RestoreAdmissionError):
        _rollback(recovery, prepared)

    assert _live(workspace) == before
    assert workspace.gate.blocked()
    assert linked.exists()


def test_rollback_is_self_contained_when_original_archive_and_staging_are_missing(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    before = _live(workspace)
    recovery, prepared = _interrupted_apply(workspace, monkeypatch, after_installs=3)
    staged = Path(workspace.plan.staged_path)
    for entry in workspace.manifest.entries:
        (staged / entry.relative_path).unlink()
    (staged / "documents").rmdir()
    (staged / "database").rmdir()
    staged.rmdir()
    Path(workspace.manifest.archive_path).unlink()
    assert recovery.inspect(prepared.operation_id)["rollback_supported"] is True

    _rollback(recovery, prepared)

    assert _live(workspace) == before
    assert not workspace.gate.blocked()


def test_real_process_crash_during_apply_then_rollback_converges_to_original_bytes(
    changed_workspace: Workspace,
) -> None:
    workspace = changed_workspace
    before = _live(workspace)
    apply_script = f"""
import os
from job_apply_pro.desktop_entry import restore
from job_apply_pro.services.restore_rollback import RestoreRollback
original = RestoreRollback._install
def stop(self, prepared, target, image):
    original(self, prepared, target, image)
    if target.path == prepared.source.database:
        os._exit(77)
RestoreRollback._install = stop
restore({workspace.plan.id!r}, {workspace.plan.fingerprint!r})
"""
    result = run(workspace.root, "-c", apply_script)
    assert result.returncode == 77, result.stderr
    operation_id = workspace.gate.active_id()
    host = _host(workspace)
    fingerprint = host.inspect(operation_id)["review_fingerprint"]
    assert isinstance(fingerprint, str)
    rollback_script = f"""
import os
from job_apply_pro.desktop_entry import restore_rollback
from job_apply_pro.services.restore_rollback import RestoreRollback
original = RestoreRollback._install
def stop(self, prepared, target, image):
    original(self, prepared, target, image)
    os._exit(78)
RestoreRollback._install = stop
restore_rollback({operation_id!r}, {fingerprint!r})
"""
    result = run(workspace.root, "-c", rollback_script)
    assert result.returncode == 78, result.stderr
    assert workspace.gate.blocked()
    result = cli(
        workspace.root,
        "restore-rollback",
        "--operation-id",
        operation_id,
        "--fingerprint",
        fingerprint,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert _live(workspace) == before
    assert not workspace.gate.blocked()


def test_actual_concurrent_recovery_commands_cannot_enter_owning_rollback_lease(
    changed_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = changed_workspace
    before = _live(workspace)
    recovery, prepared = _interrupted_apply(workspace, monkeypatch, after_installs=3)
    fingerprint = recovery._review_fingerprint(prepared)
    script = f"""
import sys
from job_apply_pro.desktop_entry import restore_rollback
from job_apply_pro.services.restore_rollback import RestoreRollback
original = RestoreRollback._install
paused = False
def pause(self, model, target, image):
    global paused
    original(self, model, target, image)
    if not paused:
        paused = True
        print('ROLLBACK_OWNS_LEASE', flush=True)
        if sys.stdin.readline() != 'continue\\n':
            raise RuntimeError('Test owner did not receive its release')
RestoreRollback._install = pause
restore_rollback({prepared.operation_id!r}, {fingerprint!r})
"""
    owner = subprocess.Popen(
        [sys.executable, "-c", script],
        env=environment(workspace.root),
        cwd=workspace.root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert owner.stdout is not None
    output_reader = ThreadPoolExecutor(max_workers=1)
    try:
        boundary = output_reader.submit(owner.stdout.readline).result(timeout=20)
        assert boundary == "ROLLBACK_OWNS_LEASE\n"
        while_owned = _live(workspace)
        for command in ("restore-inspect", "restore-rollback", "restore-finalize"):
            arguments = [command, "--operation-id", prepared.operation_id]
            if command == "restore-rollback":
                arguments += ["--fingerprint", fingerprint]
            competitor = cli(workspace.root, *arguments)
            assert competitor.returncode == 3, competitor.stderr
            assert competitor.stdout == ""
            assert competitor.stderr.startswith("Offline restore admission failed.")
            assert _live(workspace) == while_owned
            assert workspace.gate.blocked()
        stdout, stderr = owner.communicate("continue\n", timeout=20)
        assert owner.returncode == 0, stderr
        assert stdout == ""
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=20)
        output_reader.shutdown(wait=True)
    assert _live(workspace) == before
    assert not workspace.gate.blocked()
