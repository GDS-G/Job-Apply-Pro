param(
    [string]$OutputDirectory = "release"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$target = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot $OutputDirectory))
if (-not $target.StartsWith($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output directory must be inside the repository."
}
New-Item -ItemType Directory -Force -Path $target | Out-Null

$installers = @(Get-ChildItem -LiteralPath $target -Filter "Job-Apply-Pro-*.exe" -File)
if ($installers.Count -eq 0) { throw "No Job Apply Pro installer was found in $target" }

$hashLines = foreach ($installer in $installers) {
    $signature = Get-AuthenticodeSignature -LiteralPath $installer.FullName
    if ($signature.Status -ne "Valid") {
        throw "Installer signature is not valid: $($installer.Name) ($($signature.Status))"
    }
    $hash = Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256
    "$($hash.Hash.ToLowerInvariant())  $($installer.Name)"
}
Set-Content -LiteralPath (Join-Path $target "SHA256SUMS.txt") -Value $hashLines -Encoding utf8

Push-Location $repositoryRoot
try {
    & pnpm licenses list --json | Set-Content -LiteralPath (Join-Path $target "node-dependencies.json") -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "Node dependency inventory failed." }
    & python -m pip inspect | Set-Content -LiteralPath (Join-Path $target "python-dependencies.json") -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "Python dependency inventory failed." }
}
finally {
    Pop-Location
}
