param(
    [string]$PythonPath = ""
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$distPath = Join-Path $repoRoot "apps\desktop\backend-dist"
$workPath = Join-Path $repoRoot ".pyinstaller"
$specPath = Join-Path $PSScriptRoot "job_apply_pro_backend.spec"
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $localPython = Join-Path $repoRoot ".venv-dev\Scripts\python.exe"
    $PythonPath = if (Test-Path -LiteralPath $localPython -PathType Leaf) { $localPython } else { "python" }
}

Push-Location $repoRoot
try {
    & $PythonPath -m PyInstaller --noconfirm --clean --distpath $distPath --workpath $workPath $specPath
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
