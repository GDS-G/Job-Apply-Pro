from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from job_apply_pro import desktop_entry
from job_apply_pro.browser import client as client_module
from job_apply_pro.browser.client import (
    FROZEN_BROWSER_WORKER_NAME,
    BrowserWorkerClient,
    BrowserWorkerUnavailableError,
)


def _capture_launch(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    process = Mock()
    process.poll.return_value = None
    spawn = Mock(return_value=process)
    reader = Mock()
    monkeypatch.setattr("job_apply_pro.browser.client.subprocess.Popen", spawn)
    monkeypatch.setattr("job_apply_pro.browser.client.threading.Thread", reader)
    return spawn, reader


@pytest.mark.parametrize("existing_python_path", [None, "synthetic-source-extension"])
def test_source_worker_keeps_python_module_launch(
    monkeypatch: pytest.MonkeyPatch, existing_python_path: str | None
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    if existing_python_path is None:
        monkeypatch.delenv("PYTHONPATH", raising=False)
    else:
        monkeypatch.setenv("PYTHONPATH", existing_python_path)
    spawn, reader = _capture_launch(monkeypatch)
    worker = BrowserWorkerClient()

    worker.start()

    source_root = Path(client_module.__file__).resolve().parents[2]
    assert spawn.call_args.args == ([sys.executable, "-m", "job_apply_pro.browser.worker_process"],)
    options = spawn.call_args.kwargs
    expected_python_path = str(source_root)
    if existing_python_path is not None:
        expected_python_path += os.pathsep + existing_python_path
    assert options["env"]["PYTHONPATH"] == expected_python_path
    assert options["cwd"] == str(source_root)
    assert options["stdin"] == options["stdout"] == subprocess.PIPE
    assert options["stderr"] == subprocess.DEVNULL
    assert options["text"] is True
    assert options["encoding"] == "utf-8"
    assert options["creationflags"] == (subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    reader.assert_called_once_with(
        target=worker._read_responses, args=(spawn.return_value,), daemon=True
    )
    reader.return_value.start.assert_called_once_with()
    worker.start()
    spawn.assert_called_once()


def test_frozen_worker_uses_fixed_sibling_and_no_source_pythonpath(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = tmp_path / "application with spaces"
    bundle.mkdir()
    backend_executable = bundle / "job-apply-pro-backend.exe"
    worker_executable = bundle / FROZEN_BROWSER_WORKER_NAME
    backend_executable.write_bytes(b"synthetic backend")
    worker_executable.write_bytes(b"synthetic worker")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(backend_executable))
    monkeypatch.setenv("PYTHONPATH", "untrusted-development-override")
    spawn, _reader = _capture_launch(monkeypatch)

    BrowserWorkerClient().start()

    assert spawn.call_args.args == ([str(worker_executable), "browser-worker"],)
    options = spawn.call_args.kwargs
    assert options["cwd"] == str(bundle)
    assert not any(key.upper() == "PYTHONPATH" for key in options["env"])
    assert options["stdin"] == options["stdout"] == subprocess.PIPE
    assert options["stderr"] == subprocess.DEVNULL
    assert options["creationflags"] == (subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


@pytest.mark.parametrize("missing_kind", ["absent", "directory"])
def test_frozen_missing_worker_fails_closed_without_path_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing_kind: str
) -> None:
    backend_executable = tmp_path / "job-apply-pro-backend.exe"
    backend_executable.write_bytes(b"synthetic backend")
    if missing_kind == "directory":
        (tmp_path / FROZEN_BROWSER_WORKER_NAME).mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / FROZEN_BROWSER_WORKER_NAME).write_bytes(b"must not be launched")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(backend_executable))
    monkeypatch.setenv("PATH", str(elsewhere))
    spawn, reader = _capture_launch(monkeypatch)
    worker = BrowserWorkerClient()

    with pytest.raises(BrowserWorkerUnavailableError, match="packaged browser worker is missing"):
        worker.start()

    assert not worker.running
    spawn.assert_not_called()
    reader.assert_not_called()


@pytest.mark.parametrize("frozen", [False, True])
def test_worker_spawn_os_error_is_controlled_and_sanitized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, frozen: bool
) -> None:
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    if frozen:
        backend_executable = tmp_path / "job-apply-pro-backend.exe"
        backend_executable.write_bytes(b"synthetic backend")
        (tmp_path / FROZEN_BROWSER_WORKER_NAME).write_bytes(b"synthetic worker")
        monkeypatch.setattr(sys, "executable", str(backend_executable))
    spawn, reader = _capture_launch(monkeypatch)
    spawn.side_effect = PermissionError("private-path-and-environment-must-not-escape")
    worker = BrowserWorkerClient()

    with pytest.raises(BrowserWorkerUnavailableError, match="could not be started") as failure:
        worker.start()

    assert "private-path" not in str(failure.value)
    assert failure.value.__suppress_context__ is True
    assert not worker.running
    reader.assert_not_called()


@pytest.mark.parametrize("failure_kind", [BrokenPipeError, ValueError])
@pytest.mark.parametrize("operation", ["write", "flush"])
def test_worker_pipe_failure_is_controlled_and_releases_response_queue(
    monkeypatch: pytest.MonkeyPatch, failure_kind: type[Exception], operation: str
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    spawn, _reader = _capture_launch(monkeypatch)
    getattr(spawn.return_value.stdin, operation).side_effect = failure_kind(
        "private-path-must-not-escape"
    )
    worker = BrowserWorkerClient()

    with pytest.raises(BrowserWorkerUnavailableError, match="input is unavailable") as failure:
        worker.call("observe", {"session_id": "synthetic-session"})

    assert "private-path" not in str(failure.value)
    assert failure.value.__suppress_context__ is True
    assert worker._responses == {}
    # Shutdown's pipe failure remains a controlled worker error, so the existing
    # termination-and-wait fallback still runs when the helper has disappeared.
    worker.close()
    spawn.return_value.terminate.assert_called_once_with()
    spawn.return_value.wait.assert_called_once_with(timeout=10)
    assert not worker.running


def test_worker_reader_keeps_exact_process_after_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    spawn, reader = _capture_launch(monkeypatch)
    first = spawn.return_value
    worker = BrowserWorkerClient()
    worker.start()
    first.poll.return_value = 0
    second = Mock()
    second.poll.return_value = None
    spawn.return_value = second

    worker.start()

    assert reader.call_args_list[0].kwargs["args"] == (first,)
    assert reader.call_args_list[1].kwargs["args"] == (second,)


@pytest.mark.parametrize("missing_stream", ["stdin", "stdout"])
def test_worker_entry_rejects_windowed_standard_streams(
    monkeypatch: pytest.MonkeyPatch, missing_stream: str
) -> None:
    monkeypatch.setattr(sys, "argv", ["synthetic-worker", "browser-worker"])
    monkeypatch.setattr(sys, missing_stream, None)

    with pytest.raises(SystemExit) as failure:
        desktop_entry.main()

    assert failure.value.code == 2


def test_worker_entry_rejects_restore_only_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys, "argv", ["synthetic-worker", "browser-worker", "--plan-id", "synthetic-plan"]
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO())

    with pytest.raises(SystemExit) as failure:
        desktop_entry.main()

    assert failure.value.code == 2


def test_frozen_windows_worker_selects_installed_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Synthetic User\AppData\Local")

    desktop_entry._configure_worker_browser_cache()

    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == (
        r"C:\Users\Synthetic User\AppData\Local\ms-playwright"
    )


@pytest.mark.parametrize("override", ["0", r"D:\reviewed-browser-cache", ""])
def test_frozen_worker_preserves_explicit_browser_cache_override(
    monkeypatch: pytest.MonkeyPatch, override: str
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", override)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    desktop_entry._configure_worker_browser_cache()

    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == override


@pytest.mark.parametrize("frozen, platform", [(False, "win32"), (True, "linux")])
def test_source_and_non_windows_cache_selection_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, frozen: bool, platform: str
) -> None:
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    desktop_entry._configure_worker_browser_cache()

    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


@pytest.mark.parametrize(
    "local_app_data",
    [None, "", "relative-cache", r"C:drive-relative", r"\root-relative", r"C:\cache\..\other"],
)
def test_missing_or_invalid_frozen_windows_cache_root_fails_closed(
    monkeypatch: pytest.MonkeyPatch, local_app_data: str | None
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    if local_app_data is None:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    else:
        monkeypatch.setenv("LOCALAPPDATA", local_app_data)

    with pytest.raises(ValueError, match="absolute Windows directory"):
        desktop_entry._configure_worker_browser_cache()

    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_worker_entry_invalid_cache_configuration_is_controlled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["synthetic-worker", "browser-worker"])
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    with pytest.raises(SystemExit) as failure:
        desktop_entry.main()

    assert failure.value.code == 2


def test_worker_entry_dispatch_isolated_from_api_and_database(tmp_path: Path) -> None:
    source_root = Path(__file__).parents[1] / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root)
    environment["JAP_DATABASE_URL"] = "synthetic-invalid-database-url"
    script = """
import json
import sys
import types

from job_apply_pro import desktop_entry

calls = []
stub = types.ModuleType("job_apply_pro.browser.worker_process")
stub.main = lambda: calls.append("worker")
sys.modules[stub.__name__] = stub
sys.argv = ["synthetic-worker", "browser-worker"]
desktop_entry.main()
print(json.dumps({
    "calls": calls,
    "api_loaded": "job_apply_pro.main" in sys.modules,
    "database_loaded": "job_apply_pro.storage.database" in sys.modules,
    "configuration_loaded": "job_apply_pro.config" in sys.modules,
    "migration_loaded": "alembic" in sys.modules,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input="",
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
        env=environment,
        cwd=tmp_path,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert json.loads(result.stdout) == {
        "calls": ["worker"],
        "api_loaded": False,
        "database_loaded": False,
        "configuration_loaded": False,
        "migration_loaded": False,
    }
    assert list(tmp_path.iterdir()) == []


def test_packaging_spec_shares_archive_and_collects_both_executables() -> None:
    spec = Path(__file__).parents[1] / "job_apply_pro_backend.spec"
    syntax = ast.parse(spec.read_text(encoding="utf-8"))
    executable_calls = [
        node
        for node in ast.walk(syntax)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "EXE"
    ]
    assert len(executable_calls) == 2
    options = [
        {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}
        for call in executable_calls
    ]
    assert [(item["name"], item["console"]) for item in options] == [
        ("job-apply-pro-backend", False),
        ("job-apply-pro-browser-worker", True),
    ]
    assert all(item["exclude_binaries"] is True for item in options)
    for call in executable_calls:
        assert isinstance(call.args[0], ast.Name) and call.args[0].id == "pyz"
        assert isinstance(call.args[1], ast.Attribute) and call.args[1].attr == "scripts"
        assert isinstance(call.args[1].value, ast.Name) and call.args[1].value.id == "analysis"
    collect = next(
        node
        for node in ast.walk(syntax)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "COLLECT"
    )
    assert [node.id for node in collect.args[:2] if isinstance(node, ast.Name)] == [
        "executable",
        "browser_worker_executable",
    ]
