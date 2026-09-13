"""DB-independent restore admission. This is a gate, not a rollback transaction."""

from __future__ import annotations

import os
import re
import stat
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from job_apply_pro.security.encryption import SensitiveDataCipher

CONTROL_DIRECTORY = "restore-control"
GUARD_NAME = "active.guard"
MAX_RECORD_BYTES = 4 * 1024 * 1024
RECOVERY_MESSAGE = (
    "Offline restore recovery is required. Keep backups, staging files and the original key. "
    "Normal startup and updates are blocked until authenticated completion can be verified."
)


class RestoreAdmissionError(RuntimeError):
    pass


def checked_path(path: Path, *, root: Path | None = None) -> Path:
    """Reject aliases; not handle-pinned isolation from non-cooperating local mutations."""
    absolute = Path(os.path.abspath(path))
    if os.name == "nt" and str(absolute).startswith("\\\\"):
        raise RestoreAdmissionError(
            "Restore requires an app-owned local workspace, not a network path"
        )
    if sys.platform == "win32":
        import ctypes

        if ctypes.windll.kernel32.GetDriveTypeW(str(absolute.anchor)) not in {2, 3}:
            raise RestoreAdmissionError("Restore admission requires an available local drive")
    for component in (absolute, *absolute.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise RestoreAdmissionError("Workspace path cannot be inspected safely") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise RestoreAdmissionError(
                "Restore does not support linked or redirected workspace paths"
            )
    resolved = absolute.resolve()
    if root is not None and (resolved == root or root not in resolved.parents):
        raise RestoreAdmissionError("Restore path is outside its app-owned workspace")
    return resolved


def safe_relative(value: str) -> Path:
    parts = value.split("/")
    reserved = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)
    if len(value) > 512 or any(
        not part
        or part in {".", ".."}
        or part.endswith((".", " "))
        or reserved.match(part)
        or any(ord(c) < 32 or c in '\\:<>"|?*' for c in part)
        for part in parts
    ):
        raise RestoreAdmissionError("Restore contains an unsupported relative path")
    return Path(*parts)


def sync_directory(directory: Path) -> None:
    # Windows file fsync uses _commit. Directory fsync is POSIX-only; this does
    # not promise arbitrary hardware/power-loss or multi-file atomicity.
    if os.name != "nt":
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def write_exclusive(path: Path, data: bytes) -> None:
    checked_path(path)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def atomic_write_exclusive(path: Path, data: bytes) -> None:
    """Publish complete bytes under the cooperative exclusive workspace lease.

    Failed or interrupted pending siblings are retained as recovery evidence.
    This does not add handle-pinned protection against non-cooperating path races.
    """
    root = _restore_owner.get()
    if root is None:
        raise RestoreAdmissionError("An exclusive restore workspace lease is required")
    _require_restore_lease(root)
    try:
        final = checked_path(path, root=root)
        if not stat.S_ISDIR(final.parent.lstat().st_mode):
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        try:
            final.lstat()
        except FileNotFoundError:
            pass
        else:
            raise RestoreAdmissionError("A published restore object already exists")
        pending = checked_path(final.with_name(f".{final.name}.{uuid4()}.pending"), root=root)
        with pending.open("xb") as stream:
            if stream.write(data) != len(data):
                raise RestoreAdmissionError("Restore object could not be written completely")
            stream.flush()
            os.fsync(stream.fileno())
        _require_restore_lease(root)
        checked_path(pending, root=root)
        checked_path(final, root=root)
        try:
            final.lstat()
        except FileNotFoundError:
            pass
        else:
            raise RestoreAdmissionError("A published restore object already exists")
        # The lease excludes cooperative writers between the final existence
        # check and rename. Windows rename also refuses an existing destination.
        pending.rename(final)
        sync_directory(final.parent)
    except OSError:
        raise RestoreAdmissionError("Restore object could not be published safely") from None


class RestoreGateRepository:
    def __init__(self, workspace_root: Path) -> None:
        self.root = checked_path(workspace_root)
        self.control = self.root / CONTROL_DIRECTORY
        self.guard = self.control / GUARD_NAME

    def blocked(self) -> bool:
        try:
            checked_path(self.control, root=self.root)
            self.guard.lstat()
            return True
        except FileNotFoundError:
            return False
        except (OSError, RestoreAdmissionError):
            return True

    def assert_clear(self) -> None:
        if self.blocked():
            raise RestoreAdmissionError(RECOVERY_MESSAGE)

    def active_id(self) -> str:
        try:
            checked_path(self.guard, root=self.root)
            with self.guard.open("rb") as stream:
                value = stream.read(129).decode("ascii").strip()
            if len(value) > 36 or str(UUID(value)) != value:
                raise ValueError
            return value
        except (OSError, ValueError, UnicodeError):
            raise RestoreAdmissionError(RECOVERY_MESSAGE) from None

    def operation_path(self, operation_id: str) -> Path:
        if str(UUID(operation_id)) != operation_id:
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        return checked_path(self.control / "operations" / operation_id, root=self.root)

    def read_record(
        self, operation_id: str, kind: str, cipher: SensitiveDataCipher
    ) -> dict[str, object]:
        if kind not in {"intent", "receipt"}:
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        try:
            path = checked_path(self.operation_path(operation_id) / f"{kind}.enc", root=self.root)
            with path.open("rb") as stream:
                encoded = stream.read(MAX_RECORD_BYTES + 1)
            if len(encoded) > MAX_RECORD_BYTES:
                raise ValueError
            return cipher.decrypt_json(
                encoded.decode("ascii"), context=f"restore:v1:{operation_id}:{kind}"
            )
        except (OSError, ValueError, UnicodeError):
            raise RestoreAdmissionError(RECOVERY_MESSAGE) from None

    def write_record(
        self, operation_id: str, kind: str, value: dict[str, object], cipher: SensitiveDataCipher
    ) -> None:
        if kind not in {"intent", "receipt"}:
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        encoded = cipher.encrypt_json(value, context=f"restore:v1:{operation_id}:{kind}").encode(
            "ascii"
        )
        if len(encoded) > MAX_RECORD_BYTES:
            raise RestoreAdmissionError("Restore metadata exceeds the supported bound")
        write_exclusive(self.operation_path(operation_id) / f"{kind}.enc", encoded)

    def begin(self, intent: dict[str, object], cipher: SensitiveDataCipher) -> str:
        self.assert_clear()
        operation_id = str(uuid4())
        directory = self.operation_path(operation_id)
        directory.mkdir(parents=True, exist_ok=False)
        self.write_record(operation_id, "intent", intent, cipher)
        write_exclusive(self.guard, operation_id.encode("ascii"))
        return operation_id

    def allocate_operation(self) -> str:
        _require_restore_lease(self.root)
        self.assert_clear()
        operation_id = str(uuid4())
        directory = self.operation_path(operation_id)
        try:
            directory.parent.mkdir(parents=True, exist_ok=True)
            sync_directory(directory.parent.parent)
            checked_path(directory, root=self.root)
            directory.mkdir(exist_ok=False)
            sync_directory(directory.parent)
        except OSError:
            raise RestoreAdmissionError("Restore operation could not be allocated safely") from None
        return operation_id

    def activate_prepared(self, operation_id: str) -> None:
        _require_restore_lease(self.root)
        self.assert_clear()
        if not self.has_v2_record(operation_id, "intent"):
            raise RestoreAdmissionError("A prepared v2 restore intent is required")
        # Presence publishes a fail-closed gate, never proof of authenticated
        # completion. The service authenticates the intent before target writes.
        atomic_write_exclusive(self.guard, operation_id.encode("ascii"))

    def _v2_record_path(self, operation_id: str, kind: str) -> Path:
        if not isinstance(kind, str) or kind not in {"intent", "decision", "receipt"}:
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        try:
            return checked_path(
                self.operation_path(operation_id) / f"{kind}.v2.enc", root=self.root
            )
        except (ValueError, TypeError, AttributeError):
            raise RestoreAdmissionError(RECOVERY_MESSAGE) from None

    def has_v2_record(self, operation_id: str, kind: str) -> bool:
        path = self._v2_record_path(operation_id, kind)
        try:
            path.lstat()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            raise RestoreAdmissionError(RECOVERY_MESSAGE) from None

    def read_v2_record(
        self, operation_id: str, kind: str, cipher: SensitiveDataCipher
    ) -> dict[str, object]:
        path = self._v2_record_path(operation_id, kind)
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RestoreAdmissionError(RECOVERY_MESSAGE)
            with path.open("rb") as stream:
                encoded = stream.read(MAX_RECORD_BYTES + 1)
            if len(encoded) > MAX_RECORD_BYTES:
                raise ValueError
            return cipher.decrypt_json(
                encoded.decode("ascii"), context=f"restore:v2:{operation_id}:{kind}"
            )
        except (OSError, ValueError, UnicodeError):
            raise RestoreAdmissionError(RECOVERY_MESSAGE) from None

    def write_v2_record(
        self, operation_id: str, kind: str, value: dict[str, object], cipher: SensitiveDataCipher
    ) -> None:
        _require_restore_lease(self.root)
        path = self._v2_record_path(operation_id, kind)
        encoded = cipher.encrypt_json(value, context=f"restore:v2:{operation_id}:{kind}").encode(
            "ascii"
        )
        if len(encoded) > MAX_RECORD_BYTES:
            raise RestoreAdmissionError("Restore metadata exceeds the supported bound")
        atomic_write_exclusive(path, encoded)

    def finish_verified(self, operation_id: str) -> None:
        # Called only after authenticated receipt and all targets have been rechecked.
        if self.active_id() != operation_id:
            raise RestoreAdmissionError(RECOVERY_MESSAGE)
        self.guard.unlink()
        sync_directory(self.control)


_mutex = threading.RLock()
_leases: dict[Path, tuple[BinaryIO, str, int]] = {}
_restore_owner: ContextVar[Path | None] = ContextVar("restore_owner", default=None)


def owns_restore(root: Path) -> bool:
    return _restore_owner.get() == root


def _require_restore_lease(root: Path) -> None:
    with _mutex:
        lease = _leases.get(root)
        if not owns_restore(root) or lease is None or lease[1] != "restore":
            raise RestoreAdmissionError("An exclusive restore workspace lease is required")


@contextmanager
def workspace_access(root: Path, *, restore: bool = False) -> Iterator[None]:
    repository = RestoreGateRepository(root)
    root = repository.root
    kind = "restore" if restore else "runtime"
    with _mutex:
        existing = _leases.get(root)
        if existing:
            stream, existing_kind, count = existing
            if (existing_kind != kind and not owns_restore(root)) or (
                existing_kind == "restore" and not owns_restore(root)
            ):
                raise RestoreAdmissionError(
                    "Workspace is busy; wait for its owning process to exit"
                )
            _leases[root] = stream, existing_kind, count + 1
        else:
            checked_path(repository.control, root=root)
            repository.control.mkdir(parents=True, exist_ok=True)
            checked_path(repository.control / "admission.lock", root=root)
            stream = (repository.control / "admission.lock").open("a+b")
            try:
                stream.seek(0)
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                stream.close()
                raise RestoreAdmissionError(
                    "Workspace is busy; wait for its owning process to exit"
                ) from None
            _leases[root] = stream, kind, 1
    token = _restore_owner.set(root) if restore else None
    try:
        if not restore and not owns_restore(root):
            repository.assert_clear()
        yield
    finally:
        if token is not None:
            _restore_owner.reset(token)
        with _mutex:
            stream, kind, count = _leases[root]
            if count > 1:
                _leases[root] = stream, kind, count - 1
            else:
                del _leases[root]
                stream.close()
