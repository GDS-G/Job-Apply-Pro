param(
    [string]$BackendDirectory = "apps\desktop\backend-dist\job-apply-pro-backend",
    [string]$PythonPath = ""
)

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

function Start-SmokeBackend {
    param(
        [string]$Executable,
        [string]$StdoutPath,
        [string]$StderrPath
    )

    $started = Start-Process -FilePath $Executable -ArgumentList "serve" -WindowStyle Hidden -PassThru -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 250
        try {
            $health = Invoke-RestMethod -Uri "$apiRoot/api/v1/health" -TimeoutSec 2
        }
        catch {
            $health = $null
        }
    } while ($null -eq $health -and [DateTime]::UtcNow -lt $deadline -and -not $started.HasExited)
    if ($null -eq $health -or $health.status -ne "ok" -or $health.service -ne "job-apply-pro-backend" -or $health.environment -ne $env:JAP_ENVIRONMENT) {
        $stderrText = if (Test-Path -LiteralPath $StderrPath) { Get-Content -Raw -LiteralPath $StderrPath } else { "" }
        if (-not $started.HasExited) { $started.Kill() }
        throw "Packaged backend did not report healthy before the deadline. $stderrText"
    }
    return $started
}

function Stop-SmokeBackend {
    param(
        [System.Diagnostics.Process]$Process,
        [System.Diagnostics.Process]$WorkerProcess = $null
    )

    if ($null -eq $WorkerProcess -and $null -ne $Process -and -not $Process.HasExited) {
        $ownedWorkers = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($Process.Id)" | Where-Object {
            $_.Name -eq "job-apply-pro-browser-worker.exe" -and $_.ExecutablePath -eq $browserWorker
        })
        if ($ownedWorkers.Count -eq 1) {
            $WorkerProcess = Get-Process -Id $ownedWorkers[0].ProcessId -ErrorAction SilentlyContinue
            if ($null -ne $WorkerProcess) { $null = $WorkerProcess.Handle }
        }
    }
    if ($null -ne $Process -and -not $Process.HasExited) {
        $Process.Kill()
        if (-not $Process.WaitForExit(10000)) { throw "Packaged backend exit could not be verified" }
    }
    if ($null -ne $WorkerProcess -and -not $WorkerProcess.WaitForExit(15000)) {
        # Only this previously verified backend child is eligible for cleanup.
        $WorkerProcess.Kill()
        if (-not $WorkerProcess.WaitForExit(10000)) { throw "Packaged API-owned worker cleanup could not be verified" }
        throw "Packaged API-owned worker did not exit after its parent's IPC pipe closed"
    }
    if ($null -ne $WorkerProcess -and $WorkerProcess.ExitCode -ne 0) {
        throw "Packaged API-owned worker exited unsuccessfully after parent shutdown"
    }
}

$process = $null
$apiWorkerProcess = $null
try {
    $migration = Start-Process -FilePath $backend -ArgumentList "migrate" -WindowStyle Hidden -Wait -PassThru
    if ($migration.ExitCode -ne 0) { throw "Packaged backend migration failed" }
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
    $workerRecords = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($process.Id)" | Where-Object {
        $_.Name -eq "job-apply-pro-browser-worker.exe" -and $_.ExecutablePath -eq $browserWorker
    })
    if ($workerRecords.Count -ne 1) {
        throw "Packaged API did not retain exactly one fixed-sibling browser worker"
    }
    $apiWorkerProcess = Get-Process -Id $workerRecords[0].ProcessId -ErrorAction Stop
    $null = $apiWorkerProcess.Handle
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
    $restoreArguments = @("restore", "--plan-id", $plan.id, "--fingerprint", $plan.fingerprint)
    $restore = Start-Process -FilePath $backend -ArgumentList $restoreArguments -WindowStyle Hidden -Wait -PassThru
    if ($restore.ExitCode -ne 0) { throw "Packaged offline restore failed" }
    if ((Get-Content -Raw -LiteralPath $documentPath) -ne $originalDocument) {
        throw "Packaged offline restore did not recover the staged document"
    }
    $databasePath = Join-Path $resolvedTestRoot "smoke.db"
    if (-not (Test-Path -LiteralPath "$databasePath.pre-restore" -PathType Leaf)) {
        throw "Packaged offline restore did not retain the previous database"
    }

    $postRestoreMigration = Start-Process -FilePath $backend -ArgumentList "migrate" -WindowStyle Hidden -Wait -PassThru
    if ($postRestoreMigration.ExitCode -ne 0) { throw "Post-restore migration failed" }
    $postRestoreStdout = Join-Path $resolvedTestRoot "post-restore.stdout.log"
    $postRestoreStderr = Join-Path $resolvedTestRoot "post-restore.stderr.log"
    $process = Start-SmokeBackend -Executable $backend -StdoutPath $postRestoreStdout -StderrPath $postRestoreStderr
    $backups = @(Invoke-RestMethod -Uri "$apiRoot/api/v1/operations/backups" -Headers $headers -TimeoutSec 5)
    if ($backups.Count -ne 1 -or $backups[0].id -ne $backup.id) {
        throw "Recovered database did not retain the backup manifest"
    }
    $diagnostics = Invoke-RestMethod -Uri "$apiRoot/api/v1/operations/diagnostics" -Headers $headers -TimeoutSec 5
    if ($diagnostics.process_status -ne "READY") { throw "Post-restore diagnostics are not ready" }
    $restoredCleanup = Invoke-RestMethod -Uri "$apiRoot/api/v1/ai/media-cleanup" -Headers $headers -TimeoutSec 5
    if (@($restoredCleanup.items).Count -ne 0) { throw "Restored packaged cleanup journal is not empty" }
    $restoredMailAudits = @(Invoke-RestMethod -Uri "$apiRoot/api/v1/communications/mutation-audits" -Headers $headers -TimeoutSec 5)
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
finally {
    try {
        Stop-SmokeBackend -Process $process -WorkerProcess $apiWorkerProcess
    }
    finally {
        if (Test-Path -LiteralPath $resolvedTestRoot) {
            Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
        }
    }
}
