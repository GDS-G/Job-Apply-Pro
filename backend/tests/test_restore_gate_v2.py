"""Synthetic publication failures; no claim of arbitrary hardware durability."""

import os
from pathlib import Path
from typing import BinaryIO, cast
from uuid import UUID, uuid4

import pytest

from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.storage.restore_gate_repository import (
    MAX_RECORD_BYTES,
    RestoreAdmissionError,
    RestoreGateRepository,
    atomic_write_exclusive,
    workspace_access,
)


@pytest.fixture
def cipher() -> SensitiveDataCipher:
    return SensitiveDataCipher(StaticKeyProvider(b"v" * 32))


def test_allocate_is_canonical_and_activation_requires_published_intent(
    tmp_path: Path, cipher: SensitiveDataCipher
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        assert str(UUID(operation_id)) == operation_id
        directory = gate.control / "operations" / operation_id
        assert gate.operation_path(operation_id) == directory
        assert directory.is_dir() and not gate.blocked()
        with pytest.raises(RestoreAdmissionError, match="prepared v2"):
            gate.activate_prepared(operation_id)
        assert not gate.blocked()
        gate.write_v2_record(operation_id, "intent", {"id": operation_id}, cipher)
        gate.activate_prepared(operation_id)
        assert gate.blocked() and gate.active_id() == operation_id
        assert gate.guard.read_bytes() == operation_id.encode("ascii")
        before = list((gate.control / "operations").iterdir())
        with pytest.raises(RestoreAdmissionError):
            gate.allocate_operation()
        with pytest.raises(RestoreAdmissionError):
            gate.activate_prepared(str(uuid4()))
        assert list((gate.control / "operations").iterdir()) == before
        assert gate.active_id() == operation_id


def test_allocation_counts_retained_evidence_and_enforces_global_quota(
    tmp_path: Path, cipher: SensitiveDataCipher, monkeypatch: pytest.MonkeyPatch
) -> None:
    import job_apply_pro.storage.restore_gate_repository as module

    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        gate.write_v2_record(operation_id, "intent", {"retained": True}, cipher)
        retained = (gate.operation_path(operation_id) / "intent.v2.enc").stat().st_size
        monkeypatch.setattr(module, "MAX_RETAINED_RECOVERY_BYTES", retained + 10)
        monkeypatch.setattr(module, "MAX_NEW_RECOVERY_BYTES", 11)
        before = list((gate.control / "operations").iterdir())

        with pytest.raises(RestoreAdmissionError, match="bounded quota"):
            gate.allocate_operation()

        assert list((gate.control / "operations").iterdir()) == before


@pytest.mark.parametrize("limit", ["retained-bytes", "operation-bytes", "files"])
def test_v2_record_publication_counts_pending_siblings_before_writing(
    tmp_path: Path,
    cipher: SensitiveDataCipher,
    monkeypatch: pytest.MonkeyPatch,
    limit: str,
) -> None:
    import job_apply_pro.storage.restore_gate_repository as module

    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        operation = gate.operation_path(operation_id)
        pending = operation / f".intent.v2.enc.{uuid4()}.pending"
        pending.write_bytes(b"retained interrupted publication")
        before = {path.name: path.read_bytes() for path in operation.iterdir()}
        if limit == "retained-bytes":
            monkeypatch.setattr(
                module,
                "MAX_RETAINED_RECOVERY_BYTES",
                pending.stat().st_size + 1,
            )
        elif limit == "operation-bytes":
            monkeypatch.setattr(
                module,
                "MAX_NEW_RECOVERY_BYTES",
                pending.stat().st_size + 1,
            )
        else:
            monkeypatch.setattr(module, "MAX_RECOVERY_FILES_PER_OPERATION", 1)

        with pytest.raises(RestoreAdmissionError, match="bounded quota"):
            gate.write_v2_record(operation_id, "intent", {"new": True}, cipher)

        assert {path.name: path.read_bytes() for path in operation.iterdir()} == before


def test_unknown_retained_inventory_fails_closed_before_new_allocation(tmp_path: Path) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        unexpected = gate.operation_path(operation_id) / "unreviewed.private"
        unexpected.write_bytes(b"unknown recovery residue")

        with pytest.raises(RestoreAdmissionError):
            gate.allocate_operation()

        assert unexpected.read_bytes() == b"unknown recovery residue"


@pytest.mark.parametrize("kind", ["intent", "decision", "receipt"])
def test_v2_records_are_context_bound_exclusive_and_readable_without_a_lease(
    tmp_path: Path, cipher: SensitiveDataCipher, kind: str
) -> None:
    gate = RestoreGateRepository(tmp_path)
    value: dict[str, object] = {"kind": kind, "synthetic_private_data": "reviewed state"}
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        gate.write_v2_record(operation_id, kind, value, cipher)
        path = gate.operation_path(operation_id) / f"{kind}.v2.enc"
        original = path.read_bytes()
        assert b"synthetic_private_data" not in original
        assert (
            cipher.decrypt_json(
                original.decode("ascii"), context=f"restore:v2:{operation_id}:{kind}"
            )
            == value
        )
        with pytest.raises(RestoreAdmissionError, match="already exists"):
            gate.write_v2_record(operation_id, kind, {"overwrite": True}, cipher)
        assert path.read_bytes() == original
        assert not list(path.parent.glob("*.pending"))
    assert gate.has_v2_record(operation_id, kind)
    assert gate.read_v2_record(operation_id, kind, cipher) == value


@pytest.mark.parametrize("kind", ["intent", "decision", "receipt"])
def test_hardlinked_v2_records_remain_present_but_cannot_be_read(
    tmp_path: Path, cipher: SensitiveDataCipher, kind: str
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        gate.write_v2_record(operation_id, kind, {"bound": True}, cipher)
    path = gate.operation_path(operation_id) / f"{kind}.v2.enc"
    original = path.read_bytes()
    alias = tmp_path / f"{kind}.alias"
    alias.hardlink_to(path)
    assert path.stat().st_nlink == 2
    assert gate.has_v2_record(operation_id, kind)
    with pytest.raises(RestoreAdmissionError):
        gate.read_v2_record(operation_id, kind, cipher)
    assert path.read_bytes() == alias.read_bytes() == original
    assert path.stat().st_nlink == 2


def test_interrupted_pending_records_are_preserved_ignored_and_never_activate(
    tmp_path: Path, cipher: SensitiveDataCipher
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        pending = gate.operation_path(operation_id) / f".intent.v2.enc.{uuid4()}.pending"
        pending.write_bytes(b"partial encrypted envelope")
        assert not gate.has_v2_record(operation_id, "intent")
        with pytest.raises(RestoreAdmissionError):
            gate.read_v2_record(operation_id, "intent", cipher)
        with pytest.raises(RestoreAdmissionError):
            gate.activate_prepared(operation_id)
        assert not gate.blocked()
        gate.write_v2_record(operation_id, "intent", {"complete": True}, cipher)
        assert pending.read_bytes() == b"partial encrypted envelope"
        assert gate.read_v2_record(operation_id, "intent", cipher) == {"complete": True}


class _InterruptedWriter:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream

    def __enter__(self) -> "_InterruptedWriter":
        return self

    def __exit__(self, *args: object) -> None:
        self.stream.close()

    def write(self, data: bytes) -> int:
        self.stream.write(data[: len(data) // 2])
        self.stream.flush()
        raise OSError("synthetic interrupted write")


def test_midwrite_failure_does_not_publish_partial_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        final = gate.operation_path(operation_id) / "decision.v2.enc"
        original_open = Path.open

        def interrupted_open(path: Path, mode: str = "r") -> BinaryIO:
            return cast(BinaryIO, _InterruptedWriter(cast(BinaryIO, original_open(path, mode))))

        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", interrupted_open)
            with pytest.raises(RestoreAdmissionError, match="published safely"):
                atomic_write_exclusive(final, b"complete-object")
        assert not final.exists() and not gate.has_v2_record(operation_id, "decision")
        pending = list(final.parent.glob("*.pending"))
        assert len(pending) == 1 and pending[0].read_bytes() == b"complet"


@pytest.mark.parametrize("failure", ["fsync", "rename"])
def test_unpublished_complete_object_survives_publication_failure(
    tmp_path: Path, cipher: SensitiveDataCipher, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        final = gate.operation_path(operation_id) / "intent.v2.enc"

        def fail(*args: object) -> None:
            raise OSError("synthetic publication failure")

        with monkeypatch.context() as patch:
            if failure == "fsync":
                patch.setattr(os, "fsync", fail)
            else:
                patch.setattr(Path, "rename", fail)
            with pytest.raises(RestoreAdmissionError):
                gate.write_v2_record(operation_id, "intent", {"state": "complete"}, cipher)
        assert not final.exists() and not gate.has_v2_record(operation_id, "intent")
        pending = list(final.parent.glob("*.pending"))
        assert len(pending) == 1
        before = pending[0].read_bytes()
        assert cipher.decrypt_json(
            before.decode("ascii"), context=f"restore:v2:{operation_id}:intent"
        ) == {"state": "complete"}
        gate.write_v2_record(operation_id, "intent", {"state": "retry"}, cipher)
        assert pending[0].read_bytes() == before
        assert gate.read_v2_record(operation_id, "intent", cipher) == {"state": "retry"}


def test_final_is_rechecked_after_fsync_and_an_existing_record_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        final = gate.operation_path(operation_id) / "receipt.v2.enc"
        fsync = os.fsync

        def publish_prior(descriptor: int) -> None:
            fsync(descriptor)
            final.write_bytes(b"previous publication")

        monkeypatch.setattr(os, "fsync", publish_prior)
        with pytest.raises(RestoreAdmissionError, match="already exists"):
            atomic_write_exclusive(final, b"replacement must not win")
        assert final.read_bytes() == b"previous publication"
        assert [path.read_bytes() for path in final.parent.glob("*.pending")] == [
            b"replacement must not win"
        ]


def test_parent_sync_failure_keeps_complete_final_and_retry_cannot_replace_it(
    tmp_path: Path, cipher: SensitiveDataCipher, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()

        def fail(_directory: Path) -> None:
            raise OSError("synthetic directory-sync failure")

        with monkeypatch.context() as patch:
            patch.setattr("job_apply_pro.storage.restore_gate_repository.sync_directory", fail)
            with pytest.raises(RestoreAdmissionError):
                gate.write_v2_record(operation_id, "receipt", {"published": True}, cipher)
        assert gate.has_v2_record(operation_id, "receipt")
        assert gate.read_v2_record(operation_id, "receipt", cipher) == {"published": True}
        with pytest.raises(RestoreAdmissionError):
            gate.write_v2_record(operation_id, "receipt", {"replace": True}, cipher)
        assert gate.read_v2_record(operation_id, "receipt", cipher) == {"published": True}


@pytest.mark.parametrize("kind", ["unknown", "decision.enc", "../intent", "", "INTENT"])
def test_unknown_v2_kinds_fail_closed(
    tmp_path: Path, cipher: SensitiveDataCipher, kind: str
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        with pytest.raises(RestoreAdmissionError):
            gate.write_v2_record(operation_id, kind, {}, cipher)
        with pytest.raises(RestoreAdmissionError):
            gate.read_v2_record(operation_id, kind, cipher)
        with pytest.raises(RestoreAdmissionError):
            gate.has_v2_record(operation_id, kind)
        assert not list(gate.operation_path(operation_id).iterdir())


@pytest.mark.parametrize("operation_id", ["", "../escape", "not-a-uuid", str(uuid4()).upper()])
def test_noncanonical_v2_operation_ids_fail_closed(tmp_path: Path, operation_id: str) -> None:
    with pytest.raises(RestoreAdmissionError):
        RestoreGateRepository(tmp_path).has_v2_record(operation_id, "intent")


@pytest.mark.parametrize("corruption", ["empty", "invalid", "non-ascii", "oversized", "directory"])
def test_present_corrupt_records_are_never_treated_as_absent(
    tmp_path: Path, cipher: SensitiveDataCipher, corruption: str
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        path = gate.operation_path(operation_id) / "intent.v2.enc"
        if corruption == "directory":
            path.mkdir()
        else:
            path.write_bytes(
                {
                    "empty": b"",
                    "invalid": b"broken",
                    "non-ascii": b"\xff",
                    "oversized": b"a" * (MAX_RECORD_BYTES + 1),
                }[corruption]
            )
        assert gate.has_v2_record(operation_id, "intent")
        with pytest.raises(RestoreAdmissionError):
            gate.read_v2_record(operation_id, "intent", cipher)
        with pytest.raises(RestoreAdmissionError):
            gate.write_v2_record(operation_id, "intent", {"replace": True}, cipher)


def test_record_presence_inspection_errors_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
    target = gate.operation_path(operation_id) / "receipt.v2.enc"
    lstat = Path.lstat

    def inaccessible(path: Path) -> os.stat_result:
        if path == target:
            raise PermissionError("synthetic inspection denial")
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", inaccessible)
    with pytest.raises(RestoreAdmissionError):
        gate.has_v2_record(operation_id, "receipt")


def test_wrong_key_and_record_context_fail_closed(
    tmp_path: Path, cipher: SensitiveDataCipher
) -> None:
    gate = RestoreGateRepository(tmp_path)
    wrong_key = SensitiveDataCipher(StaticKeyProvider(b"w" * 32))
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        gate.write_v2_record(operation_id, "intent", {"bound": True}, cipher)
        source = gate.operation_path(operation_id) / "intent.v2.enc"
        (source.parent / "receipt.v2.enc").write_bytes(source.read_bytes())
        with pytest.raises(RestoreAdmissionError):
            gate.read_v2_record(operation_id, "intent", wrong_key)
        with pytest.raises(RestoreAdmissionError):
            gate.read_v2_record(operation_id, "receipt", cipher)
        assert gate.has_v2_record(operation_id, "intent") and gate.has_v2_record(
            operation_id, "receipt"
        )


def test_v2_record_write_keeps_existing_encrypted_size_bound(
    tmp_path: Path, cipher: SensitiveDataCipher
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()
        with pytest.raises(RestoreAdmissionError, match="supported bound"):
            gate.write_v2_record(operation_id, "intent", {"large": "a" * MAX_RECORD_BYTES}, cipher)
        assert not gate.has_v2_record(operation_id, "intent")
        assert not list(gate.operation_path(operation_id).iterdir())


@pytest.mark.parametrize("lease", ["none", "runtime", "other-root"])
def test_v2_mutations_require_the_owning_exclusive_restore_lease(
    tmp_path: Path, cipher: SensitiveDataCipher, lease: str
) -> None:
    gate = RestoreGateRepository(tmp_path)
    with workspace_access(tmp_path, restore=True):
        operation_id = gate.allocate_operation()

    def denied() -> None:
        with pytest.raises(RestoreAdmissionError):
            gate.allocate_operation()
        with pytest.raises(RestoreAdmissionError):
            gate.write_v2_record(operation_id, "intent", {}, cipher)
        with pytest.raises(RestoreAdmissionError):
            gate.activate_prepared(operation_id)
        with pytest.raises(RestoreAdmissionError):
            atomic_write_exclusive(gate.operation_path(operation_id) / "object.enc", b"data")

    if lease == "none":
        denied()
    else:
        root = tmp_path if lease == "runtime" else tmp_path / "other-root"
        with workspace_access(root, restore=lease != "runtime"):
            denied()
    assert not gate.blocked() and not list(gate.operation_path(operation_id).iterdir())


def test_v1_apis_and_contexts_remain_unchanged(tmp_path: Path, cipher: SensitiveDataCipher) -> None:
    gate = RestoreGateRepository(tmp_path)
    operation_id = gate.begin({"version": 1}, cipher)
    gate.write_record(operation_id, "receipt", {"old_receipt": True}, cipher)
    assert gate.active_id() == operation_id
    directory = gate.operation_path(operation_id)
    assert sorted(path.name for path in directory.iterdir()) == ["intent.enc", "receipt.enc"]
    assert cipher.decrypt_json(
        (directory / "intent.enc").read_text("ascii"), context=f"restore:v1:{operation_id}:intent"
    ) == {"version": 1}
    assert gate.read_record(operation_id, "receipt", cipher) == {"old_receipt": True}
    assert not gate.has_v2_record(operation_id, "receipt")
    with pytest.raises(RestoreAdmissionError):
        gate.read_v2_record(operation_id, "intent", cipher)
    with pytest.raises(RestoreAdmissionError):
        gate.write_record(operation_id, "decision", {}, cipher)
    gate.finish_verified(operation_id)
    assert not gate.blocked()
    assert (directory / "intent.enc").exists() and (directory / "receipt.enc").exists()
