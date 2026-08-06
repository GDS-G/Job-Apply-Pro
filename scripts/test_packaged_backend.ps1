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

$process = $null
try {
    $migration = Start-Process -FilePath $backend -ArgumentList "migrate" -WindowStyle Hidden -Wait -PassThru
    if ($migration.ExitCode -ne 0) { throw "Packaged backend migration failed" }
    $stdoutPath = Join-Path $resolvedTestRoot "backend.stdout.log"
    $stderrPath = Join-Path $resolvedTestRoot "backend.stderr.log"
    $process = Start-Process -FilePath $backend -ArgumentList "serve" -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 250
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:8876/api/v1/health" -TimeoutSec 2
        }
        catch {
            $response = $null
        }
    } while ($null -eq $response -and [DateTime]::UtcNow -lt $deadline -and -not $process.HasExited)
    if ($null -eq $response -or $response.status -ne "ok") {
        $stderrText = if (Test-Path -LiteralPath $stderrPath) { Get-Content -Raw -LiteralPath $stderrPath } else { "" }
        throw "Packaged backend did not report healthy before the deadline. $stderrText"
    }
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
    }
    if (Test-Path -LiteralPath $resolvedTestRoot) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
