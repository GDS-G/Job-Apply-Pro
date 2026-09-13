"""Deterministic smoke-wrapper ownership tests; never launch a packaged process."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "test_packaged_backend.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")

HARNESS = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '__SCRIPT__', [ref]$tokens, [ref]$errors
)
if ($errors.Count -ne 0) { throw 'Smoke wrapper did not parse' }
$names = @('Initialize-SmokeLifecycle', 'Start-SmokeBackend',
           'Stop-SmokeBackend', 'Complete-SmokeCleanup')
$definitions = $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $names -contains $node.Name
}, $true)
if ($definitions.Count -ne 4) { throw 'Expected lifecycle functions were not found' }
foreach ($definition in $definitions) {
    # Test-only substitution leaves the production Process boundary strongly typed.
    $source = $definition.Extent.Text.Replace('System.Diagnostics.Process', 'object')
    . ([scriptblock]::Create($source))
}

class FakeProcess {
    [int]$Id = 6100
    [int]$Handle = 7100
    [bool]$HasExited = $false
    [bool]$WaitResult = $true
    [bool]$WaitThrows = $false
    [bool]$KillThrows = $false
    [bool]$ExitOnKill = $true
    [int]$ExitCode = 0
    [int]$KillCalls = 0
    [Collections.Generic.List[int]]$Waits = [Collections.Generic.List[int]]::new()
    [void] Kill() {
        $this.KillCalls += 1
        if ($this.KillThrows) { throw 'synthetic private kill detail' }
        if ($this.ExitOnKill) { $this.HasExited = $true }
    }
    [bool] WaitForExit([int]$milliseconds) {
        $this.Waits.Add($milliseconds)
        if ($this.WaitThrows) { throw 'synthetic private wait detail' }
        if ($this.WaitResult) { $this.HasExited = $true }
        return $this.WaitResult
    }
}
$script:backend = [FakeProcess]::new()
$script:worker = [FakeProcess]::new()
$script:worker.Id = 6200
$script:spawnThrows = $false
$script:cimThrows = $false
$script:discoverWorker = $false
$script:deleteCalls = 0
$script:spawnCalls = 0
$script:hidden = $false
$script:lastError = ''
$script:health = [pscustomobject]@{
    status = 'ok'; service = 'job-apply-pro-backend'; environment = 'synthetic'
}
$browserWorker = 'C:\synthetic\job-apply-pro-browser-worker.exe'
$apiRoot = 'http://127.0.0.1:1'
$env:JAP_ENVIRONMENT = 'synthetic'
$directory = Join-Path ([IO.Path]::GetTempPath()) 'job-apply-pro-package-smoke-synthetic'

function Start-Process {
    param($FilePath, $ArgumentList, $WindowStyle, [switch]$PassThru,
          $RedirectStandardOutput, $RedirectStandardError, $ErrorAction)
    $script:spawnCalls += 1
    $script:hidden = $WindowStyle -eq 'Hidden'
    if ($script:spawnThrows) { throw 'synthetic private startup detail' }
    return $script:backend
}
function Start-Sleep { param($Milliseconds) }
function Invoke-RestMethod { param($Uri, $TimeoutSec) return $script:health }
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($script:cimThrows) { throw 'synthetic private inspection detail' }
    if ($script:discoverWorker) {
        return [pscustomobject]@{
            Name = 'job-apply-pro-browser-worker.exe'
            ExecutablePath = $browserWorker
            ProcessId = $script:worker.Id
        }
    }
}
function Get-Process { param($Id, $ErrorAction) return $script:worker }
function Test-Path { param($LiteralPath) return $true }
function Remove-Item {
    param($LiteralPath, [switch]$Recurse, [switch]$Force, $ErrorAction)
    $script:deleteCalls += 1
}
function Capture-Failure {
    param([scriptblock]$Action)
    try { & $Action | Out-Null }
    catch { $script:lastError = $_.Exception.Message }
}
Initialize-SmokeLifecycle
__SCENARIO__
[pscustomobject]@{
    deleted = $script:deleteCalls
    retained = $script:smokePreserveArtifacts
    backend_owners = $script:smokeOwnedBackends.Count
    worker_owners = $script:smokeOwnedWorkers.Count
    backend_kills = $script:backend.KillCalls
    worker_kills = $script:worker.KillCalls
    backend_waits = @($script:backend.Waits.ToArray())
    worker_waits = @($script:worker.Waits.ToArray())
    spawn_calls = $script:spawnCalls
    hidden = $script:hidden
    message = $script:lastError
} | ConvertTo-Json -Compress
"""


def run_lifecycle(scenario: str) -> dict[str, Any]:
    assert POWERSHELL is not None
    source = HARNESS.replace("__SCRIPT__", str(SCRIPT).replace("'", "''")).replace(
        "__SCENARIO__", scenario
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", source],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    decoded: dict[str, Any] = json.loads(result.stdout.strip())
    assert "synthetic private" not in decoded["message"]
    assert all(value in {10_000, 15_000} for value in decoded["backend_waits"])
    assert all(value in {10_000, 15_000} for value in decoded["worker_waits"])
    return decoded


def test_normal_startup_and_exit_proof_allow_cleanup() -> None:
    result = run_lifecycle(
        """
$owned = Start-SmokeBackend -Executable 'synthetic.exe' -StdoutPath 'out' -StderrPath 'err'
Stop-SmokeBackend -Process $owned
Complete-SmokeCleanup -Directory $directory
"""
    )
    assert result["deleted"] == 1
    assert result["retained"] is False
    assert result["backend_owners"] == 1
    assert result["backend_kills"] == 1
    assert result["backend_waits"] == [10_000, 10_000]
    assert result["spawn_calls"] == 1
    assert result["hidden"] is True


@pytest.mark.parametrize("health", ["$null", "[pscustomobject]@{status='wrong'}"])
def test_failed_or_timed_out_startup_retains_handle_until_bounded_exit(health: str) -> None:
    result = run_lifecycle(
        f"$script:health = {health}\n"
        + """
Capture-Failure {
    $lost = Start-SmokeBackend -Executable 'synthetic.exe' -StdoutPath 'out' `
        -StderrPath 'err' -StartupTimeoutMilliseconds 1
}
Complete-SmokeCleanup -Directory $directory
"""
    )
    assert result["backend_owners"] == 1
    assert result["backend_kills"] == 1
    assert result["backend_waits"] == [10_000, 10_000]
    assert result["deleted"] == 1
    assert "startup failed" in result["message"]


def test_startup_failure_without_exit_proof_never_deletes_workspace() -> None:
    result = run_lifecycle(
        """
$script:health = [pscustomobject]@{status='wrong'}
$script:backend.WaitResult = $false
$script:backend.ExitOnKill = $false
Capture-Failure {
    $lost = Start-SmokeBackend -Executable 'synthetic.exe' -StdoutPath 'out' -StderrPath 'err'
}
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["backend_owners"] == 1
    assert result["backend_kills"] == 2
    assert result["backend_waits"] == [10_000, 10_000]
    assert result["deleted"] == 0
    assert result["retained"] is True


@pytest.mark.parametrize("failure", ["KillThrows", "WaitThrows", "WaitResult"])
def test_failed_shutdown_retention_is_sticky_after_later_exit_proof(failure: str) -> None:
    value = "$false" if failure == "WaitResult" else "$true"
    result = run_lifecycle(
        f"$script:backend.{failure} = {value}\n"
        + """
Capture-Failure { Stop-SmokeBackend -Process $script:backend }
$script:backend.KillThrows = $false
$script:backend.WaitThrows = $false
$script:backend.WaitResult = $true
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert len(result["backend_waits"]) == 2
    assert result["deleted"] == 0
    assert result["retained"] is True
    assert "preserved" in result["message"]


def test_backend_failure_does_not_abandon_captured_worker_cleanup() -> None:
    result = run_lifecycle(
        """
$script:backend.WaitResult = $false
$script:backend.ExitOnKill = $false
Capture-Failure { Stop-SmokeBackend -Process $script:backend -WorkerProcess $script:worker }
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["worker_owners"] == 1
    assert result["worker_waits"] == [15_000, 15_000]
    assert result["deleted"] == 0
    assert result["retained"] is True


def test_nonzero_worker_exit_preserves_workspace_despite_exit_proof() -> None:
    result = run_lifecycle(
        """
$script:worker.ExitCode = 1
Capture-Failure { Stop-SmokeBackend -Process $script:backend -WorkerProcess $script:worker }
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["worker_waits"] == [15_000, 15_000]
    assert result["deleted"] == 0
    assert result["retained"] is True


def test_worker_kill_refusal_still_requires_bounded_exit_observation() -> None:
    result = run_lifecycle(
        """
$script:worker.WaitResult = $false
$script:worker.KillThrows = $true
Capture-Failure { Stop-SmokeBackend -Process $script:backend -WorkerProcess $script:worker }
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["worker_waits"] == [15_000, 10_000, 15_000, 10_000]
    assert result["worker_kills"] == 2
    assert result["deleted"] == 0


def test_exceptional_creation_without_a_handle_preserves_workspace() -> None:
    result = run_lifecycle(
        """
$script:spawnThrows = $true
Capture-Failure {
    Start-SmokeBackend -Executable 'synthetic.exe' -StdoutPath 'out' -StderrPath 'err'
}
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["backend_owners"] == 0
    assert result["backend_kills"] == 0
    assert result["deleted"] == 0
    assert result["retained"] is True


def test_worker_discovery_failure_does_not_skip_backend_exit_observation() -> None:
    result = run_lifecycle(
        """
$script:cimThrows = $true
Capture-Failure { Stop-SmokeBackend -Process $script:backend }
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["backend_kills"] == 1
    assert result["backend_waits"] == [10_000, 10_000]
    assert result["deleted"] == 0
    assert result["retained"] is True


def test_exact_discovered_worker_is_captured_before_shutdown() -> None:
    result = run_lifecycle(
        """
$script:discoverWorker = $true
Stop-SmokeBackend -Process $script:backend
Complete-SmokeCleanup -Directory $directory
"""
    )
    assert result["worker_owners"] == 1
    assert result["worker_kills"] == 0
    assert result["worker_waits"] == [15_000, 15_000]
    assert result["deleted"] == 1


def test_cleanup_does_not_abandon_second_backend_after_first_failure() -> None:
    result = run_lifecycle(
        """
$second = [FakeProcess]::new()
$script:backend.WaitResult = $false
$script:backend.ExitOnKill = $false
$script:smokeOwnedBackends.Add($script:backend)
$script:smokeOwnedBackends.Add($second)
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
if ($second.Waits.Count -ne 1 -or $second.KillCalls -ne 1) {
    throw 'Second captured backend was abandoned'
}
"""
    )
    assert result["backend_owners"] == 2
    assert result["deleted"] == 0
    assert result["retained"] is True
