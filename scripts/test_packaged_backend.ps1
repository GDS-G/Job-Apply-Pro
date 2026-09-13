param(
    [string]$BackendDirectory = "apps\desktop\backend-dist\job-apply-pro-backend",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$bundleRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot $BackendDirectory))
$repoPrefix = $repoRoot.TrimEnd("\", "/") + [IO.Path]::DirectorySeparatorChar
if (-not $bundleRoot.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Packaged backend directory must be inside this repository"
}
$backend = Join-Path $bundleRoot "job-apply-pro-backend.exe"
if (-not (Test-Path -LiteralPath $backend -PathType Leaf)) {
    throw "Packaged backend executable was not found at $backend"
}
$browserWorker = Join-Path (Split-Path -Parent $backend) "job-apply-pro-browser-worker.exe"
if (-not (Test-Path -LiteralPath $browserWorker -PathType Leaf)) {
    throw "Packaged browser worker executable was not found beside the backend"
}
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $localPython = Join-Path $repoRoot ".venv-dev\Scripts\python.exe"
    $PythonPath = if (Test-Path -LiteralPath $localPython -PathType Leaf) { $localPython } else { "python" }
}

$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("job-apply-pro-package-smoke-" + [guid]::NewGuid())
$resolvedTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
if (-not $resolvedTestRoot.StartsWith($resolvedTempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a package smoke directory outside the system temp directory"
}

New-Item -ItemType Directory -Path $resolvedTestRoot | Out-Null
$env:JAP_WORKSPACE_ROOT = $resolvedTestRoot
$env:JAP_DATABASE_URL = "sqlite:///" + (Join-Path $resolvedTestRoot "smoke.db").Replace("\", "/")
$env:JAP_BROWSER_DATA_DIR = Join-Path $resolvedTestRoot "browser"
$env:JAP_BROWSER_ARTIFACT_DIR = Join-Path $resolvedTestRoot "artifacts"
$env:JAP_DOCUMENT_DATA_DIR = Join-Path $resolvedTestRoot "documents"
$env:JAP_BACKUP_DATA_DIR = Join-Path $resolvedTestRoot "backups"
$env:JAP_RESTORE_STAGING_DIR = Join-Path $resolvedTestRoot "restore"
$env:JAP_API_HOST = "127.0.0.1"
$env:JAP_ENVIRONMENT = "package-smoke-" + [guid]::NewGuid().ToString("N")
$portProbe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$portProbe.Start()
$env:JAP_API_PORT = ([Net.IPEndPoint]$portProbe.LocalEndpoint).Port.ToString()
$portProbe.Stop()
$apiRoot = "http://127.0.0.1:$($env:JAP_API_PORT)"
$env:JAP_API_TOKEN = "package-smoke-token"
$env:JAP_MASTER_KEY = [Convert]::ToBase64String([byte[]](1..32))
$env:JAP_AI_CONFIG_JSON = '{"providers":[],"models":[],"policies":[]}'
$env:JAP_COMMUNICATION_CONFIG_JSON = '{"providers":[],"oauth_clients":[]}'
$env:JAP_AUTOMATION_ENABLED = "false"
$env:JAP_BROWSER_HEADLESS = "true"

function Initialize-SmokeLifecycle {
    $script:smokeOwnedBackends = [Collections.Generic.List[System.Diagnostics.Process]]::new()
    $script:smokePinnedBackends = [Collections.Generic.List[System.Diagnostics.Process]]::new()
    $script:smokeOwnedWorkers = [Collections.Generic.List[System.Diagnostics.Process]]::new()
    $script:smokeWorkerParents = [Collections.Generic.Dictionary[System.Diagnostics.Process, System.Diagnostics.Process]]::new()
    $script:smokeOwnedCommands = [Collections.Generic.List[System.Diagnostics.Process]]::new()
    $script:smokePreserveArtifacts = $false
}

function Get-SmokeWorker {
    param([System.Diagnostics.Process]$Parent)

    try {
        if ($null -eq $Parent -or -not $script:smokeOwnedBackends.Contains($Parent) -or
            -not $script:smokePinnedBackends.Contains($Parent)) {
            throw "Worker parent is not a captured backend"
        }
        # Reuse only the previously verified handle, even after its parent exits.
        # This smoke does not request browser work/restart after capture; the old
        # handle is never evidence for an unobserved replacement worker.
        if ($script:smokeWorkerParents.ContainsKey($Parent)) {
            return $script:smokeWorkerParents[$Parent]
        }
        $parentHandle = $Parent.Handle
        if ($null -eq $parentHandle -or $parentHandle -eq 0) { throw "Parent handle could not be pinned" }
        if ($Parent.HasExited) { throw "Worker parent already exited" }
        $parentStarted = $Parent.StartTime.ToUniversalTime()
        $records = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($Parent.Id)" -ErrorAction Stop | Where-Object {
            $_.Name -eq "job-apply-pro-browser-worker.exe"
        })
        if ($records.Count -gt 1) { throw "Ambiguous API worker ownership" }
        if ($records.Count -eq 0) { return $null }
        $record = $records[0]
        if ($record.ParentProcessId -ne $Parent.Id -or $record.ExecutablePath -ne $browserWorker -or
            $record.CreationDate -isnot [datetime] -or $record.CreationDate.Kind -eq [DateTimeKind]::Unspecified) {
            throw "Incomplete API worker identity"
        }
        $candidate = Get-Process -Id $record.ProcessId -ErrorAction Stop
        if ($null -eq $candidate) { throw "API worker handle unavailable" }
        # CIM is only a discovery hint: its PID may already have been reused.
        # Pin first, then compare the actual executable and creation identity.
        $candidateHandle = $candidate.Handle
        if ($null -eq $candidateHandle -or $candidateHandle -eq 0) { throw "Worker handle could not be pinned" }
        if ($candidate.HasExited) { throw "API worker exited before capture" }
        $actualPath = $candidate.MainModule.FileName
        $actualStarted = $candidate.StartTime.ToUniversalTime()
        $recordStarted = $record.CreationDate.ToUniversalTime()
        # CIM truncates creation time to microseconds; .NET retains 100 ns ticks.
        $actualTicks = $actualStarted.Ticks - ($actualStarted.Ticks % 10)
        $recordTicks = $recordStarted.Ticks - ($recordStarted.Ticks % 10)
        if ($candidate.Id -ne $record.ProcessId -or $actualPath -ne $browserWorker -or
            $actualTicks -ne $recordTicks -or $actualStarted -lt $parentStarted -or
            $actualStarted -gt [datetime]::UtcNow -or $candidate.HasExited -or
            $Parent.HasExited -or $Parent.StartTime.ToUniversalTime() -ne $parentStarted) {
            throw "API worker identity changed during capture"
        }
        # Never register or return an object whose pinned identity was unverified.
        $script:smokeOwnedWorkers.Add($candidate)
        $script:smokeWorkerParents.Add($Parent, $candidate)
        return $candidate
    }
    catch {
        $script:smokePreserveArtifacts = $true
        throw "Packaged API worker ownership could not be verified. Preserve the synthetic workspace."
    }
}

function Wait-SmokeCommand {
    param(
        [System.Diagnostics.Process]$Process,
        [ValidateRange(1, 120000)][int]$TimeoutMilliseconds = 120000
    )

    try {
        if ($null -eq $Process -or -not $script:smokeOwnedCommands.Contains($Process)) {
            throw "Command handle is not owned"
        }
        $commandHandle = $Process.Handle
        if ($null -eq $commandHandle -or $commandHandle -eq 0) { throw "Command handle could not be pinned" }
        if (-not $Process.WaitForExit($TimeoutMilliseconds) -or $Process.ExitCode -ne 0) {
            throw "Command did not complete successfully"
        }
    }
    catch {
        # Migration/restore may have written multiple files. Never kill a writer
        # on an observation deadline or treat acceptance of a kill as exit proof.
        $script:smokePreserveArtifacts = $true
        throw "Packaged command failed or its exit is unproved. Preserve the synthetic workspace and captured writer; do not restart or delete its evidence."
    }
}

function Invoke-SmokeCommand {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [ValidateRange(1, 120000)][int]$TimeoutMilliseconds = 120000
    )

    try {
        $started = Start-Process -FilePath $Executable -ArgumentList $Arguments -WindowStyle Hidden -PassThru -ErrorAction Stop
        if ($null -eq $started) { throw "Command returned no process handle" }
        # No Start-Process -Wait assignment gap: retain before observing exit.
        $script:smokeOwnedCommands.Add($started)
        $commandHandle = $started.Handle
        if ($null -eq $commandHandle -or $commandHandle -eq 0) { throw "Command handle could not be pinned" }
        Wait-SmokeCommand -Process $started -TimeoutMilliseconds $TimeoutMilliseconds
    }
    catch {
        $script:smokePreserveArtifacts = $true
        throw "Packaged command failed or its exit is unproved. Preserve the synthetic workspace and captured writer; do not restart or delete its evidence."
    }
}

function Start-SmokeBackend {
    param(
        [string]$Executable,
        [string]$StdoutPath,
        [string]$StderrPath,
        [ValidateRange(1, 60000)][int]$StartupTimeoutMilliseconds = 60000
    )

    $started = $null
    try {
        $started = Start-Process -FilePath $Executable -ArgumentList "serve" -WindowStyle Hidden -PassThru -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath -ErrorAction Stop
        if ($null -eq $started) { throw "No owned backend handle was returned" }
        # Retain the exact handle even if startup throws before the caller's
        # assignment completes. Never recover ownership by image-name lookup.
        $script:smokeOwnedBackends.Add($started)
        $backendHandle = $started.Handle
        if ($null -eq $backendHandle -or $backendHandle -eq 0) { throw "Backend handle could not be pinned" }
        $script:smokePinnedBackends.Add($started)
        $observation = [Diagnostics.Stopwatch]::StartNew()
        do {
            Start-Sleep -Milliseconds 250
            try {
                $health = Invoke-RestMethod -Uri "$apiRoot/api/v1/health" -TimeoutSec 2
            }
            catch {
                $health = $null
            }
        } while ($null -eq $health -and $observation.ElapsedMilliseconds -lt $StartupTimeoutMilliseconds -and -not $started.HasExited)
        if ($null -eq $health -or $started.HasExited -or $health.status -ne "ok" -or $health.service -ne "job-apply-pro-backend" -or $health.environment -ne $env:JAP_ENVIRONMENT) {
            throw "Packaged backend did not report its expected healthy identity"
        }
        return $started
    }
    catch {
        $script:smokePreserveArtifacts = $true
        if ($null -ne $started) {
            try { Stop-SmokeBackend -Process $started }
            catch { $script:smokePreserveArtifacts = $true }
        }
        throw "Packaged backend startup failed. Preserve the synthetic workspace for review."
    }
}

function Stop-SmokeBackend {
    param(
        [System.Diagnostics.Process]$Process,
        [System.Diagnostics.Process]$WorkerProcess = $null
    )

    $failed = $false
    $ownedProcess = $null
    $ownedWorker = $null
    try {
        if ($null -ne $Process) {
            if (-not $script:smokeOwnedBackends.Contains($Process) -or -not $script:smokePinnedBackends.Contains($Process)) {
                throw "Backend handle is not owned and pinned"
            }
            $ownedProcess = $Process
        }
        if ($null -ne $WorkerProcess) {
            if (-not $script:smokeOwnedWorkers.Contains($WorkerProcess)) { throw "Worker handle is not verified" }
            $ownedWorker = $WorkerProcess
        } elseif ($null -ne $ownedProcess -and -not $ownedProcess.HasExited) {
            $ownedWorker = Get-SmokeWorker -Parent $ownedProcess
        }
    } catch { $failed = $true }
    if ($null -ne $ownedProcess) {
        try { if (-not $ownedProcess.HasExited) { $ownedProcess.Kill() } }
        catch { $failed = $true }
        # Kill acceptance (or failure) is never substituted for exit proof.
        try { if (-not $ownedProcess.WaitForExit(10000)) { $failed = $true } }
        catch { $failed = $true }
    }
    if ($null -ne $ownedWorker) {
        try {
            # Workers normally close after backend pipe EOF. This helper neither
            # force-kills a discovered worker nor claims process-tree containment.
            if (-not $ownedWorker.WaitForExit(15000)) {
                $failed = $true
            } elseif ($ownedWorker.ExitCode -ne 0) {
                $failed = $true
            }
        } catch { $failed = $true }
    }
    if ($failed) {
        $script:smokePreserveArtifacts = $true
        throw "Packaged smoke shutdown failed or captured process exit is unproved. Preserve the synthetic workspace until recovery is reviewed."
    }
}

function Complete-SmokeCleanup {
    param([string]$Directory)

    foreach ($ownedBackend in @($script:smokeOwnedBackends.ToArray())) {
        try { Stop-SmokeBackend -Process $ownedBackend }
        catch { $script:smokePreserveArtifacts = $true }
    }
    foreach ($ownedWorker in @($script:smokeOwnedWorkers.ToArray())) {
        try { Stop-SmokeBackend -WorkerProcess $ownedWorker }
        catch { $script:smokePreserveArtifacts = $true }
    }
    foreach ($ownedCommand in @($script:smokeOwnedCommands.ToArray())) {
        try { Wait-SmokeCommand -Process $ownedCommand -TimeoutMilliseconds 1000 }
        catch { $script:smokePreserveArtifacts = $true }
    }
    if ($script:smokePreserveArtifacts) {
        throw "Synthetic smoke workspace preserved after smoke verification failure, failed shutdown, or missing exit proof. Do not delete its artifacts until captured processes have exited and the failure is reviewed."
    }
    $absoluteDirectory = [IO.Path]::GetFullPath($Directory)
    $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd("\", "/") + [IO.Path]::DirectorySeparatorChar
    if (-not $absoluteDirectory.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -or -not ([IO.Path]::GetFileName($absoluteDirectory)).StartsWith("job-apply-pro-package-smoke-", [StringComparison]::Ordinal)) {
        throw "Refusing cleanup outside the owned synthetic smoke workspace"
    }
    if (Test-Path -LiteralPath $absoluteDirectory) {
        Remove-Item -LiteralPath $absoluteDirectory -Recurse -Force -ErrorAction Stop
    }
}

Initialize-SmokeLifecycle

# This helper authenticates synthetic restore evidence without opening SQLite or
# printing keys, decrypted bytes, filesystem paths, or database hashes.
$restoreEvidenceScript = @'
import base64
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def verify_restore_evidence(root, operation_id, expected_hash, expected_size, plan_id):
    root = Path(root).resolve(strict=True)
    if str(UUID(operation_id)) != operation_id:
        raise ValueError("Invalid operation identifier")
    control = root / "restore-control"
    operation = control / "operations" / operation_id
    for path in (control, operation.parent, operation):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Invalid restore evidence directory")
    try:
        (control / "active.guard").lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValueError("Restore remains blocked")
    key = base64.b64decode(os.environ["JAP_MASTER_KEY"], validate=True)

    def decrypt(name, kind):
        path = operation / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 384 * 1024 * 1024:
            raise ValueError("Invalid restore evidence file")
        if getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Invalid restore evidence file")
        parts = path.read_text(encoding="ascii").split(":", 3)
        if len(parts) != 4 or parts[:3] != ["jap", "v1", "local-v1"]:
            raise ValueError("Invalid restore evidence envelope")
        payload = base64.urlsafe_b64decode(parts[3])
        return AESGCM(key).decrypt(
            payload[:12], payload[12:], f"restore:v1:{operation_id}:{kind}".encode()
        )

    previous = decrypt("database-preimage.enc", "database-preimage")
    if len(previous) != int(expected_size) or hashlib.sha256(previous).hexdigest() != expected_hash.lower():
        raise ValueError("Previous database was not preserved exactly")
    intent = json.loads(decrypt("intent.enc", "intent"))
    receipt = json.loads(decrypt("receipt.enc", "receipt"))
    if intent["version"] != 1 or receipt["version"] != 1 or intent["plan"]["id"] != plan_id:
        raise ValueError("Restore evidence does not match the reviewed plan")
    if Path(intent["workspace"]) != root:
        raise ValueError("Restore evidence belongs to another workspace")
    intent["plan"]["categories"] = sorted(intent["plan"]["categories"])
    intent["manifest"]["categories"] = sorted(intent["manifest"]["categories"])
    canonical = json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != receipt["intent_sha256"]:
        raise ValueError("Restore receipt does not authenticate its intent")
    database_targets = [target for target in receipt["targets"] if target["path"] == intent["database"]]
    if len(database_targets) != 1:
        raise ValueError("Restore receipt does not identify the committed database")
    database = root / intent["database"]
    if database.parent.resolve(strict=True) != root:
        raise ValueError("Restore database is outside the smoke workspace")
    database_info = database.lstat()
    if not stat.S_ISREG(database_info.st_mode) or database_info.st_nlink != 1 or getattr(database_info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Invalid committed database file")
    actual = database.read_bytes()
    if len(actual) != database_targets[0]["size"] or hashlib.sha256(actual).hexdigest() != database_targets[0]["sha256"]:
        raise ValueError("Committed database no longer matches its receipt")


if __name__ == "__main__":
    try:
        verify_restore_evidence(*sys.argv[1:])
    except Exception:
        print("Packaged durable restore evidence verification failed.", file=sys.stderr)
        raise SystemExit(1) from None
'@

$process = $null
$apiWorkerProcess = $null
try {
    Invoke-SmokeCommand -Executable $backend -Arguments @("migrate")
    # Migration need not initialize runtime document storage. This directory is
    # fixed beneath the newly created, isolated synthetic workspace above.
    New-Item -ItemType Directory -Path $env:JAP_DOCUMENT_DATA_DIR -Force -ErrorAction Stop | Out-Null
    $documentPath = Join-Path $env:JAP_DOCUMENT_DATA_DIR "restore-smoke.enc"
    $originalDocument = "verified-packaged-restore-fixture"
    Set-Content -LiteralPath $documentPath -Value $originalDocument -Encoding utf8 -NoNewline
    $stdoutPath = Join-Path $resolvedTestRoot "backend.stdout.log"
    $stderrPath = Join-Path $resolvedTestRoot "backend.stderr.log"
    $process = Start-SmokeBackend -Executable $backend -StdoutPath $stdoutPath -StderrPath $stderrPath

    $headers = @{ "X-Job-Apply-Pro-Token" = $env:JAP_API_TOKEN }
    $cleanup = Invoke-RestMethod -Uri "$apiRoot/api/v1/ai/media-cleanup" -Headers $headers -TimeoutSec 5
    if (@($cleanup.items).Count -ne 0) { throw "Fresh packaged cleanup journal is not empty" }
    $cleanupRetry = Invoke-RestMethod -Method Post -Uri "$apiRoot/api/v1/ai/media-cleanup/retry" -Headers $headers -TimeoutSec 5
    if (@($cleanupRetry.items).Count -ne 0) { throw "Empty packaged cleanup retry changed state" }
    # Synthetic pixels only. The deliberately unknown prompt stops before any
    # route/provider work, but only after successful packaged image decoding.
    $mediaCases = @(
        @{
            data = "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGNk5+BkYGBgYgADAAFIABwHDoKrAAAAAElFTkSuQmCC"
            detail = "Prompt is missing or does not match the task type"
        },
        @{
            data = [Convert]::ToBase64String([byte[]](137, 80, 78, 71, 13, 10, 26, 10))
            detail = "Request validation failed; check required fields and supported values"
        }
    )
    foreach ($mediaCase in $mediaCases) {
        $mediaBody = @{
            task_type = "ANSWER"
            prompt_id = "package-smoke-deliberately-unknown-prompt"
            input_data = @{}
            media_upload_consent = $true
            input_parts = @(@{ kind = "media"; mime_type = "image/png"; data = $mediaCase.data })
        } | ConvertTo-Json -Depth 5
        try {
            Invoke-RestMethod -Method Post -Uri "$apiRoot/api/v1/ai/invoke" -Headers $headers -ContentType "application/json" -Body $mediaBody -TimeoutSec 10 | Out-Null
            throw "Packaged synthetic media check unexpectedly invoked a model"
        }
        catch {
            if ($null -eq $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 422) { throw }
            $mediaError = $_.ErrorDetails.Message | ConvertFrom-Json
            if ($mediaError.detail -ne $mediaCase.detail) { throw "Packaged image decoding or safe rejection failed" }
        }
    }
    & $PythonPath (Join-Path $PSScriptRoot "test_packaged_browser.py") --worker $browserWorker --test-root $resolvedTestRoot --api-url $apiRoot
    if ($LASTEXITCODE -ne 0) { throw "Packaged loopback browser smoke failed" }
    $apiWorkerProcess = Get-SmokeWorker -Parent $process
    if ($null -eq $apiWorkerProcess) {
        throw "Packaged API did not retain exactly one fixed-sibling browser worker"
    }
    & $PythonPath (Join-Path $PSScriptRoot "test_packaged_mail.py") --api-url $apiRoot
    if ($LASTEXITCODE -ne 0) { throw "Packaged verified mail attachment smoke failed" }
    $backupBody = @{
        label = "Packaged restore smoke"
        categories = @("DATABASE", "DOCUMENTS")
    } | ConvertTo-Json
    $backup = Invoke-RestMethod -Method Post -Uri "$apiRoot/api/v1/operations/backups" -Headers $headers -ContentType "application/json" -Body $backupBody
    if ($backup.status -ne "VERIFIED") { throw "Packaged backup did not verify" }
    $restoreBody = @{ categories = @("DATABASE", "DOCUMENTS") } | ConvertTo-Json
    $plan = Invoke-RestMethod -Method Post -Uri "$apiRoot/api/v1/operations/backups/$($backup.id)/restore-plans" -Headers $headers -ContentType "application/json" -Body $restoreBody
    if ($plan.status -ne "STAGED") { throw "Packaged restore plan was not staged" }

    Set-Content -LiteralPath $documentPath -Value "damaged" -Encoding utf8 -NoNewline
    Stop-SmokeBackend -Process $process -WorkerProcess $apiWorkerProcess
    $process = $null
    $apiWorkerProcess = $null
    $databasePath = Join-Path $resolvedTestRoot "smoke.db"
    $previousDatabaseHash = (Get-FileHash -LiteralPath $databasePath -Algorithm SHA256).Hash
    $previousDatabaseSize = (Get-Item -LiteralPath $databasePath).Length
    $restoreOperationsPath = Join-Path $resolvedTestRoot "restore-control\operations"
    $previousRestoreOperations = if (Test-Path -LiteralPath $restoreOperationsPath) {
        @(Get-ChildItem -LiteralPath $restoreOperationsPath -Directory | Select-Object -ExpandProperty Name)
    } else { @() }
    $restoreArguments = @("restore", "--plan-id", $plan.id, "--fingerprint", $plan.fingerprint)
    Invoke-SmokeCommand -Executable $backend -Arguments $restoreArguments
    if ((Get-Content -Raw -LiteralPath $documentPath) -ne $originalDocument) {
        throw "Packaged offline restore did not recover the staged document"
    }
    if (-not (Test-Path -LiteralPath $restoreOperationsPath -PathType Container)) {
        throw "Packaged offline restore did not retain durable recovery evidence"
    }
    $freshRestoreOperations = @(Get-ChildItem -LiteralPath $restoreOperationsPath -Directory | Where-Object { $_.Name -notin $previousRestoreOperations })
    if ($freshRestoreOperations.Count -ne 1) {
        throw "Packaged offline restore did not create exactly one fresh recovery operation"
    }
    if (Test-Path -LiteralPath "$databasePath.pre-restore") {
        throw "Packaged offline restore unexpectedly created a plaintext database recovery copy"
    }
    & $PythonPath -c $restoreEvidenceScript $resolvedTestRoot $freshRestoreOperations[0].Name $previousDatabaseHash $previousDatabaseSize $plan.id
    if ($LASTEXITCODE -ne 0) { throw "Packaged offline restore evidence failed authenticated verification" }

    Invoke-SmokeCommand -Executable $backend -Arguments @("migrate")
    $postRestoreStdout = Join-Path $resolvedTestRoot "post-restore.stdout.log"
    $postRestoreStderr = Join-Path $resolvedTestRoot "post-restore.stderr.log"
    $process = Start-SmokeBackend -Executable $backend -StdoutPath $postRestoreStdout -StderrPath $postRestoreStderr
    $backups = @(Invoke-RestMethod -Uri "$apiRoot/api/v1/operations/backups" -Headers $headers -TimeoutSec 5 | ForEach-Object { $_ })
    if ($backups.Count -ne 1 -or $backups[0].id -ne $backup.id) {
        throw "Recovered database did not retain the backup manifest"
    }
    $diagnostics = Invoke-RestMethod -Uri "$apiRoot/api/v1/operations/diagnostics" -Headers $headers -TimeoutSec 5
    if ($diagnostics.process_status -ne "READY") { throw "Post-restore diagnostics are not ready" }
    $restoredCleanup = Invoke-RestMethod -Uri "$apiRoot/api/v1/ai/media-cleanup" -Headers $headers -TimeoutSec 5
    if (@($restoredCleanup.items).Count -ne 0) { throw "Restored packaged cleanup journal is not empty" }
    # Windows PowerShell emits a JSON array as one pipeline object; enumerate
    # it explicitly before checking count and replaying individual audit rows.
    $restoredMailAudits = @(Invoke-RestMethod -Uri "$apiRoot/api/v1/communications/mutation-audits" -Headers $headers -TimeoutSec 5 | ForEach-Object { $_ })
    if ($restoredMailAudits.Count -ne 2) { throw "Restored packaged mail history is incomplete" }
    foreach ($mailAudit in $restoredMailAudits) {
        if ($mailAudit.status -ne "FAILED" -or $mailAudit.error_code -ne "ProviderNotConfiguredError" -or $null -ne $mailAudit.provider_resource_id) {
            throw "Restored packaged mail history changed its failed outcome"
        }
        $mailReplayBody = @{
            fingerprint = $mailAudit.fingerprint
            idempotency_key = $mailAudit.idempotency_key
            confirmed_by = "synthetic-package-probe"
        } | ConvertTo-Json
        $mailReplay = Invoke-RestMethod -Method Post -Uri "$apiRoot/api/v1/communications/drafts/$($mailAudit.resource_id)/send" -Headers $headers -ContentType "application/json" -Body $mailReplayBody -TimeoutSec 5
        if ($mailReplay.id -ne $mailAudit.id -or $mailReplay.status -ne "FAILED") {
            throw "Restored packaged mail attempt did not replay its original outcome"
        }
    }
    Write-Output "Packaged startup, migration, image decoding/rejection, cleanup API, loopback browser/worker lifecycle, verified mail attachment review, encrypted backup and offline restore smoke passed."
}
catch {
    # Functional verification failures also need their logs and recovery evidence,
    # even when every captured process subsequently exits successfully.
    $script:smokePreserveArtifacts = $true
    throw
}
finally {
    try {
        Stop-SmokeBackend -Process $process -WorkerProcess $apiWorkerProcess
    }
    catch { $script:smokePreserveArtifacts = $true }
    Complete-SmokeCleanup -Directory $resolvedTestRoot
}
