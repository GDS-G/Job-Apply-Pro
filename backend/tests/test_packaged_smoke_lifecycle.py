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
           'Stop-SmokeBackend', 'Complete-SmokeCleanup', 'Get-SmokeWorker',
           'Invoke-SmokeCommand', 'Wait-SmokeCommand')
$definitions = $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $names -contains $node.Name
}, $true)
if ($definitions.Count -ne 7) { throw 'Expected lifecycle functions were not found' }
foreach ($definition in $definitions) {
    # Test-only substitution leaves the production Process boundary strongly typed.
    $source = $definition.Extent.Text.Replace('System.Diagnostics.Process', 'object')
    . ([scriptblock]::Create($source))
}

class FakeProcess {
    [int]$Id = 6100
    [bool]$Pinned = $false
    [bool]$HandleThrows = $false
    [bool]$HandleZero = $false
    [bool]$ExitParentOnPin = $false
    [bool]$ChangeParentOnPin = $false
    [string]$ExecutablePath = 'C:\synthetic\job-apply-pro-browser-worker.exe'
    [datetime]$StartedUtc = [datetime]::new(2026, 1, 1, 0, 0, 2, [DateTimeKind]::Utc)
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
function New-FakeProcess {
    $fake = [FakeProcess]::new()
    $fake | Add-Member ScriptProperty Handle {
        if ($this.HandleThrows) { throw 'synthetic private handle detail' }
        if ($this.HandleZero) { return 0 }
        $this.Pinned = $true
        if ($this.ExitParentOnPin) { $script:backend.HasExited = $true }
        if ($this.ChangeParentOnPin) {
            $script:backend.StartedUtc = $script:backend.StartedUtc.AddTicks(1)
        }
        return 7100
    }
    $fake | Add-Member ScriptProperty StartTime {
        if (-not $this.Pinned) { throw 'Identity read before handle pinning' }
        return $this.StartedUtc
    }
    $fake | Add-Member ScriptProperty MainModule {
        if (-not $this.Pinned) { throw 'Identity read before handle pinning' }
        return [pscustomobject]@{ FileName = $this.ExecutablePath }
    }
    return $fake
}
$script:backend = New-FakeProcess
$script:backend.StartedUtc = $script:backend.StartedUtc.AddSeconds(-1)
$script:worker = New-FakeProcess
$script:worker.Id = 6200
$script:spawnThrows = $false
$script:cimThrows = $false
$script:discoverWorker = $false
$script:cimDate = $script:worker.StartedUtc
$script:cimParent = $script:backend.Id
$script:cimPath = $script:worker.ExecutablePath
$script:lookupCalls = 0
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
            ExecutablePath = $script:cimPath
            ProcessId = $script:worker.Id
            ParentProcessId = $script:cimParent
            CreationDate = $script:cimDate
        }
    }
}
function Get-Process {
    param($Id, $ErrorAction)
    $script:lookupCalls += 1
    return $script:worker
}
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
function Start-TestBackend {
    Start-SmokeBackend -Executable 'synthetic.exe' -StdoutPath 'out' -StderrPath 'err' | Out-Null
}
function Capture-TestWorker {
    $script:discoverWorker = $true
    Get-SmokeWorker -Parent $script:backend | Out-Null
}
Initialize-SmokeLifecycle
__SCENARIO__
[pscustomobject]@{
    deleted = $script:deleteCalls
    retained = $script:smokePreserveArtifacts
    backend_owners = $script:smokeOwnedBackends.Count
    worker_owners = $script:smokeOwnedWorkers.Count
    command_owners = $script:smokeOwnedCommands.Count
    backend_kills = $script:backend.KillCalls
    worker_kills = $script:worker.KillCalls
    backend_waits = @($script:backend.Waits.ToArray())
    worker_waits = @($script:worker.Waits.ToArray())
    spawn_calls = $script:spawnCalls
    hidden = $script:hidden
    lookups = $script:lookupCalls
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
    assert all(value in {1, 1000, 10_000, 15_000, 120_000} for value in decoded["backend_waits"])
    assert all(value in {10_000, 15_000} for value in decoded["worker_waits"])
    assert decoded["worker_kills"] == 0
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
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["backend_owners"] == 1
    assert result["backend_kills"] == 1
    assert result["backend_waits"] == [10_000, 10_000]
    assert result["deleted"] == 0
    assert result["retained"] is True


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
        f"Start-TestBackend\n$script:backend.{failure} = {value}\n"
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
Start-TestBackend
Capture-TestWorker
Capture-Failure { Stop-SmokeBackend -Process $script:backend -WorkerProcess $script:worker }
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["worker_owners"] == 1
    assert result["worker_waits"] == [15_000, 15_000, 15_000]
    assert result["deleted"] == 0
    assert result["retained"] is True


def test_nonzero_worker_exit_preserves_workspace_despite_exit_proof() -> None:
    result = run_lifecycle(
        """
$script:worker.ExitCode = 1
Start-TestBackend
Capture-TestWorker
Capture-Failure { Stop-SmokeBackend -Process $script:backend -WorkerProcess $script:worker }
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["worker_waits"] == [15_000, 15_000]
    assert result["deleted"] == 0
    assert result["retained"] is True


def test_worker_timeout_never_authorizes_kill_and_preserves_evidence() -> None:
    result = run_lifecycle(
        """
$script:worker.WaitResult = $false
$script:worker.KillThrows = $true
Start-TestBackend
Capture-TestWorker
Capture-Failure { Stop-SmokeBackend -Process $script:backend -WorkerProcess $script:worker }
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["worker_waits"] == [15_000, 15_000]
    assert result["worker_kills"] == 0
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
Start-TestBackend
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
Start-TestBackend
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
$second = New-FakeProcess
$script:backend.WaitResult = $false
$script:backend.ExitOnKill = $false
$script:smokeOwnedBackends.Add($script:backend)
$script:smokeOwnedBackends.Add($second)
$script:smokePinnedBackends.Add($script:backend)
$script:smokePinnedBackends.Add($second)
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
if ($second.Waits.Count -ne 1 -or $second.KillCalls -ne 1) {
    throw 'Second captured backend was abandoned'
}
"""
    )
    assert result["backend_owners"] == 2
    assert result["deleted"] == 0
    assert result["retained"] is True


@pytest.mark.parametrize(
    "mismatch",
    [
        "$script:worker.ExecutablePath = 'C:\\unrelated.exe'",
        "$script:worker.StartedUtc = $script:worker.StartedUtc.AddSeconds(1)",
        "$script:cimDate = $null",
        "$script:cimDate = [datetime]::SpecifyKind($script:cimDate, [DateTimeKind]::Unspecified)",
        "$script:cimParent = 9999",
        "$script:cimPath = 'C:\\unrelated.exe'",
        "$script:worker.HandleThrows = $true",
        "$script:worker.HandleZero = $true",
        "$script:worker.HasExited = $true",
        "$script:worker.ExitParentOnPin = $true",
        "$script:worker.ChangeParentOnPin = $true",
        "$script:worker.StartedUtc = $script:backend.StartedUtc.AddSeconds(-1); "
        "$script:cimDate = $script:worker.StartedUtc",
    ],
)
def test_unverified_worker_never_becomes_owned_or_observed(mismatch: str) -> None:
    result = run_lifecycle(
        "Start-TestBackend\n$script:discoverWorker = $true\n"
        + mismatch
        + """
Capture-Failure { Stop-SmokeBackend -Process $script:backend }
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["worker_owners"] == 0
    assert result["worker_waits"] == []
    assert result["backend_waits"] == [10_000, 10_000]
    assert result["deleted"] == 0
    assert result["retained"] is True


def test_matching_microsecond_identity_reuses_verified_handle_after_parent_exit() -> None:
    result = run_lifecycle(
        """
Start-TestBackend
$script:worker.StartedUtc = $script:worker.StartedUtc.AddTicks(9)
Capture-TestWorker
$script:backend.HasExited = $true
$script:cimThrows = $true
$captured = Get-SmokeWorker -Parent $script:backend
Stop-SmokeBackend -Process $script:backend -WorkerProcess $captured
Complete-SmokeCleanup -Directory $directory
"""
    )
    assert result["lookups"] == 1
    assert result["worker_owners"] == 1
    assert result["deleted"] == 1


def test_stop_rejects_supplied_unverified_worker_without_wait_or_kill() -> None:
    result = run_lifecycle(
        """
Start-TestBackend
Capture-Failure { Stop-SmokeBackend -Process $script:backend -WorkerProcess $script:worker }
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["worker_owners"] == 0
    assert result["worker_waits"] == []
    assert result["backend_kills"] == 1
    assert result["deleted"] == 0


@pytest.mark.parametrize("command", ["migrate", "restore"])
@pytest.mark.parametrize("failure", ["timeout", "wait_throw", "handle_throw", "nonzero"])
def test_cli_failure_retains_exact_writer_before_caller_assignment(
    command: str, failure: str
) -> None:
    setup = {
        "timeout": "$script:backend.WaitResult = $false",
        "wait_throw": "$script:backend.WaitThrows = $true",
        "handle_throw": "$script:backend.HandleThrows = $true",
        "nonzero": "$script:backend.ExitCode = 1",
    }[failure]
    result = run_lifecycle(
        setup
        + f"""
$script:callerReceived = $false
Capture-Failure {{
    Invoke-SmokeCommand -Executable 'synthetic.exe' -Arguments @('{command}') -TimeoutMilliseconds 1
    $script:callerReceived = $true
}}
if ($script:callerReceived) {{ throw 'Failed CLI returned success to caller' }}
Capture-Failure {{ Complete-SmokeCleanup -Directory $directory }}
"""
    )
    assert result["command_owners"] == 1
    assert result["backend_owners"] == 0
    assert result["backend_kills"] == 0
    assert result["backend_waits"] == ([] if failure == "handle_throw" else [1, 1000])
    assert result["hidden"] is True
    assert result["deleted"] == 0
    assert result["retained"] is True


def test_backend_pin_failure_never_authorizes_kill_or_speculative_wait() -> None:
    result = run_lifecycle(
        """
$script:backend.HandleThrows = $true
Capture-Failure { Start-TestBackend }
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["backend_owners"] == 1
    assert result["backend_kills"] == 0
    assert result["backend_waits"] == []
    assert result["deleted"] == 0
    assert result["retained"] is True


def test_successful_cli_is_observed_before_workspace_cleanup() -> None:
    result = run_lifecycle(
        """
Invoke-SmokeCommand -Executable 'synthetic.exe' -Arguments @('migrate')
Complete-SmokeCleanup -Directory $directory
"""
    )
    assert result["command_owners"] == 1
    assert result["backend_waits"] == [120_000, 1000]
    assert result["backend_kills"] == 0
    assert result["deleted"] == 1


def test_cli_creation_failure_without_handle_preserves_workspace() -> None:
    result = run_lifecycle(
        """
$script:spawnThrows = $true
Capture-Failure { Invoke-SmokeCommand -Executable 'synthetic.exe' -Arguments @('restore') }
Capture-Failure { Complete-SmokeCleanup -Directory $directory }
"""
    )
    assert result["command_owners"] == 0
    assert result["backend_kills"] == 0
    assert result["deleted"] == 0


def test_main_functional_failure_preserves_evidence_after_successful_shutdown() -> None:
    result = run_lifecycle(
        """
Start-TestBackend
$process = $script:backend
$apiWorkerProcess = $null
$resolvedTestRoot = $directory
$mainTry = @($ast.EndBlock.Statements | Where-Object {
    $_ -is [System.Management.Automation.Language.TryStatementAst]
})[-1]
if ($mainTry.CatchClauses.Count -ne 1) { throw 'Main failure retention handler is missing' }
# Exercise the actual wrapper catch/finally with only its functional body replaced.
$probe = 'try { throw "Synthetic receipt mismatch" } ' +
    $mainTry.CatchClauses[0].Extent.Text + ' finally ' + $mainTry.Finally.Extent.Text
Capture-Failure { . ([scriptblock]::Create($probe)) }
$commands = @($mainTry.Body.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.CommandAst]
}, $true))
if (@($commands | Where-Object { $_.GetCommandName() -eq 'Start-Process' }).Count -ne 0) {
    throw 'Main command bypasses captured lifecycle launcher'
}
if (@($commands | Where-Object { $_.GetCommandName() -eq 'Invoke-SmokeCommand' }).Count -ne 3) {
    throw 'Migration/restore command launch coverage changed'
}
if (@($commands | Where-Object { $_.GetCommandName() -eq 'Get-SmokeWorker' }).Count -ne 1) {
    throw 'Main worker capture bypasses shared verification'
}
"""
    )
    assert result["backend_kills"] == 1
    assert result["backend_waits"] == [10_000, 10_000]
    assert result["deleted"] == 0
    assert result["retained"] is True
