$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $repoRoot "apps\desktop\backend-dist\job-apply-pro-backend\job-apply-pro-backend.exe"
if (-not (Test-Path -LiteralPath $backend -PathType Leaf)) {
    throw "Packaged backend executable was not found at $backend"
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
$env:JAP_API_PORT = "8876"
$env:JAP_API_TOKEN = "package-smoke-token"
$env:JAP_MASTER_KEY = [Convert]::ToBase64String([byte[]](1..32))

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
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8876/api/v1/health" -TimeoutSec 2
        }
        catch {
            $health = $null
        }
    } while ($null -eq $health -and [DateTime]::UtcNow -lt $deadline -and -not $started.HasExited)
    if ($null -eq $health -or $health.status -ne "ok") {
        $stderrText = if (Test-Path -LiteralPath $StderrPath) { Get-Content -Raw -LiteralPath $StderrPath } else { "" }
        if (-not $started.HasExited) { Stop-Process -Id $started.Id -Force }
        throw "Packaged backend did not report healthy before the deadline. $stderrText"
    }
    return $started
}

function Stop-SmokeBackend {
    param([System.Diagnostics.Process]$Process)

    if ($null -ne $Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force
        $Process.WaitForExit()
    }
}

$process = $null
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
    $backupBody = @{
        label = "Packaged restore smoke"
        categories = @("DATABASE", "DOCUMENTS")
    } | ConvertTo-Json
    $backup = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8876/api/v1/operations/backups" -Headers $headers -ContentType "application/json" -Body $backupBody
    if ($backup.status -ne "VERIFIED") { throw "Packaged backup did not verify" }
    $restoreBody = @{ categories = @("DATABASE", "DOCUMENTS") } | ConvertTo-Json
    $plan = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8876/api/v1/operations/backups/$($backup.id)/restore-plans" -Headers $headers -ContentType "application/json" -Body $restoreBody
    if ($plan.status -ne "STAGED") { throw "Packaged restore plan was not staged" }

    Set-Content -LiteralPath $documentPath -Value "damaged" -Encoding utf8 -NoNewline
    Stop-SmokeBackend -Process $process
    $process = $null
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
    $backups = @(Invoke-RestMethod -Uri "http://127.0.0.1:8876/api/v1/operations/backups" -Headers $headers -TimeoutSec 5)
    if ($backups.Count -ne 1 -or $backups[0].id -ne $backup.id) {
        throw "Recovered database did not retain the backup manifest"
    }
    $diagnostics = Invoke-RestMethod -Uri "http://127.0.0.1:8876/api/v1/operations/diagnostics" -Headers $headers -TimeoutSec 5
    if ($diagnostics.process_status -ne "READY") { throw "Post-restore diagnostics are not ready" }
}
finally {
    Stop-SmokeBackend -Process $process
    if (Test-Path -LiteralPath $resolvedTestRoot) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
