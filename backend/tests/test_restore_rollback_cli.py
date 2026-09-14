import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from job_apply_pro import desktop_entry
from job_apply_pro.config import Settings
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.storage.restore_gate_repository import RestoreAdmissionError

_KEY = b"r" * 32
_FINGERPRINT = "a" * 64
_BLOCK_STORAGE_IMPORTS = """
import importlib.abc
import runpy
import sys

class NoRuntimeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {
            'job_apply_pro.storage.database',
            'job_apply_pro.storage.models',
            'job_apply_pro.storage.operations_repository',
            'job_apply_pro.services.backup',
            'job_apply_pro.main',
            'job_apply_pro.browser.worker_process',
            'alembic.command',
        }:
            raise AssertionError('Recovery imported forbidden runtime module: ' + fullname)

sys.meta_path.insert(0, NoRuntimeImports())
sys.argv = ['job_apply_pro.desktop_entry', *sys.argv[1:]]
runpy.run_module('job_apply_pro.desktop_entry', run_name='__main__')
"""


@pytest.fixture
def recovery_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Mock:
    import job_apply_pro.config as configuration
    import job_apply_pro.services.restore_recovery as recovery

    monkeypatch.setenv("JAP_MASTER_KEY", base64.urlsafe_b64encode(_KEY).decode("ascii"))
    settings = Settings(
        _env_file=None,
        workspace_root=tmp_path,
        database_url=f"sqlite:///{(tmp_path / 'original.db').as_posix()}",
    )
    monkeypatch.setattr(configuration, "get_settings", lambda: settings)
    service = Mock()
    factory = Mock(return_value=service)
    monkeypatch.setattr(recovery, "RestoreRecoveryService", factory)
    service.factory = factory
    return service


def test_inspection_emits_only_authenticated_service_result_using_original_key(
    recovery_service: Mock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    operation_id = str(uuid4())
    inspection = {
        "operation_id": operation_id,
        "version": 2,
        "state": "RECOVERY_REQUIRED",
        "rollback_supported": True,
        "review_fingerprint": _FINGERPRINT,
    }
    recovery_service.inspect.return_value = inspection
    monkeypatch.setattr(sys, "argv", ["backend", "restore-inspect", "--operation-id", operation_id])

    desktop_entry.main()

    recovery_service.inspect.assert_called_once_with(operation_id)
    recovery_service.rollback.assert_not_called()
    root, cipher = recovery_service.factory.call_args.args
    assert root == tmp_path
    original = SensitiveDataCipher(StaticKeyProvider(_KEY, key_id="local-v1"))
    envelope = original.encrypt_bytes(b"original-key-check", context="synthetic-cli-test")
    assert cipher.decrypt_bytes(envelope, context="synthetic-cli-test") == b"original-key-check"
    assert json.loads(capsys.readouterr().out) == inspection
    assert not (tmp_path / "original.db").exists()
    assert not (tmp_path / "secrets").exists()


def test_existing_finalize_still_delegates_only_explicit_operation(
    recovery_service: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation_id = str(uuid4())
    monkeypatch.setattr(
        sys, "argv", ["backend", "restore-finalize", "--operation-id", operation_id]
    )

    desktop_entry.main()

    recovery_service.finalize.assert_called_once_with(operation_id)
    recovery_service.inspect.assert_not_called()
    recovery_service.rollback.assert_not_called()


def test_explicit_rollback_forwards_exact_review_without_inspecting_or_finalizing(
    recovery_service: Mock, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    operation_id = str(uuid4())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backend",
            "restore-rollback",
            "--operation-id",
            operation_id,
            "--fingerprint",
            _FINGERPRINT,
        ],
    )

    desktop_entry.main()

    recovery_service.rollback.assert_called_once_with(operation_id, _FINGERPRINT)
    recovery_service.inspect.assert_not_called()
    recovery_service.finalize.assert_not_called()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("command", ["restore-inspect", "restore-rollback"])
def test_recovery_error_never_reports_success_or_retries(
    command: str,
    recovery_service: Mock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operation_id = str(uuid4())
    method = recovery_service.inspect if command == "restore-inspect" else recovery_service.rollback
    method.side_effect = RestoreAdmissionError("synthetic failure")
    arguments = ["backend", command, "--operation-id", operation_id]
    if command == "restore-rollback":
        arguments += ["--fingerprint", _FINGERPRINT]
    monkeypatch.setattr(sys, "argv", arguments)

    with pytest.raises(RestoreAdmissionError):
        desktop_entry.main()

    assert method.call_count == 1
    recovery_service.finalize.assert_not_called()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "arguments",
    [
        ["restore-inspect"],
        ["restore-rollback"],
        ["restore-rollback", "--operation-id", "operation"],
        ["restore-rollback", "--fingerprint", _FINGERPRINT],
        ["restore-inspect", "--operation-id", ""],
        ["restore-rollback", "--operation-id", "operation", "--fingerprint", ""],
        ["restore-inspect", "--operation-id", "operation", "--plan-id", "plan"],
        ["restore-inspect", "--operation-id", "operation", "--fingerprint", _FINGERPRINT],
        [
            "restore-rollback",
            "--operation-id",
            "operation",
            "--fingerprint",
            _FINGERPRINT,
            "--plan-id",
            "plan",
        ],
        ["restore-finalize", "--operation-id", "operation", "--plan-id", "plan"],
        ["restore-finalize", "--operation-id", "operation", "--fingerprint", _FINGERPRINT],
        ["restore-status", "--operation-id", "operation"],
        ["restore-status", "--plan-id", ""],
        ["restore-status", "--fingerprint", _FINGERPRINT],
    ],
)
def test_recovery_commands_reject_missing_or_unrelated_arguments_before_loading_service(
    arguments: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = Mock(side_effect=AssertionError("Recovery must not be loaded"))
    monkeypatch.setattr(desktop_entry, "_restore_recovery_service", factory)
    monkeypatch.setattr(desktop_entry, "restore_status", factory)
    monkeypatch.setattr(sys, "argv", ["backend", *arguments])

    with pytest.raises(SystemExit) as raised:
        desktop_entry.main()

    assert raised.value.code == 2
    factory.assert_not_called()


def test_recovery_requires_one_workspace_before_constructing_service(
    recovery_service: Mock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import job_apply_pro.config as configuration

    monkeypatch.setattr(
        configuration,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            workspace_root=tmp_path,
            database_url=f"sqlite:///{(tmp_path / 'other' / 'original.db').as_posix()}",
        ),
    )

    with pytest.raises(RestoreAdmissionError, match="original app-owned workspace"):
        desktop_entry.restore_inspect(str(uuid4()))

    recovery_service.factory.assert_not_called()


def _run_recovery(
    root: Path, arguments: list[str], *, key: bytes | None = _KEY
) -> subprocess.CompletedProcess[str]:
    environment = {name: value for name, value in os.environ.items() if not name.startswith("JAP_")}
    environment.update(
        {
            "JAP_DATABASE_URL": f"sqlite:///{(root / 'original.db').as_posix()}",
            "JAP_WORKSPACE_ROOT": str(root),
            "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        }
    )
    if key is not None:
        environment["JAP_MASTER_KEY"] = base64.urlsafe_b64encode(key).decode("ascii")
    return subprocess.run(
        [sys.executable, "-c", _BLOCK_STORAGE_IMPORTS, *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


@pytest.mark.parametrize("command", ["restore-inspect", "restore-rollback"])
@pytest.mark.parametrize("failure", ["missing-key", "wrong-key", "missing-guard", "invalid-uuid"])
def test_recovery_failures_are_db_free_and_never_create_a_replacement_key(
    tmp_path: Path, command: str, failure: str
) -> None:
    operation_id = str(uuid4())
    control = tmp_path / "restore-control"
    directory = control / "operations" / operation_id
    directory.mkdir(parents=True)
    cipher = SensitiveDataCipher(StaticKeyProvider(_KEY, key_id="local-v1"))
    encrypted = cipher.encrypt_json(
        {"version": 2}, context=f"restore:v1:{operation_id}:intent"
    ).encode("ascii")
    (directory / "intent.enc").write_bytes(encrypted)
    if failure != "missing-guard":
        (control / "active.guard").write_text(operation_id, encoding="ascii")
    key = None if failure == "missing-key" else b"w" * 32 if failure == "wrong-key" else _KEY
    arguments = [
        command,
        "--operation-id",
        "not-a-uuid" if failure == "invalid-uuid" else operation_id,
    ]
    if command == "restore-rollback":
        arguments += ["--fingerprint", _FINGERPRINT]

    result = _run_recovery(tmp_path, arguments, key=key)

    assert result.returncode == 3, result.stderr
    assert result.stdout == ""
    assert result.stderr.startswith("Offline restore admission failed.")
    assert "Traceback" not in result.stderr
    assert "Recovery imported forbidden" not in result.stderr
    assert not (tmp_path / "original.db").exists()
    assert not (tmp_path / "secrets").exists()
    assert (directory / "intent.enc").read_bytes() == encrypted
    assert (control / "active.guard").exists() is (failure != "missing-guard")
    assert not (directory / "receipt.enc").exists()


@pytest.mark.parametrize("blocked", [False, True])
def test_status_keeps_existing_key_free_json_shape_without_runtime_imports(
    tmp_path: Path, blocked: bool
) -> None:
    if blocked:
        control = tmp_path / "restore-control"
        control.mkdir()
        (control / "active.guard").write_text("malformed-guard", encoding="ascii")

    result = _run_recovery(tmp_path, ["restore-status"], key=None)

    assert result.returncode == (3 if blocked else 0), result.stderr
    assert json.loads(result.stdout) == {"restore_recovery_required": blocked}
    assert result.stderr == ""
    assert not (tmp_path / "original.db").exists()
    assert not (tmp_path / "secrets").exists()
