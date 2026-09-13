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
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_RESTORE_BYTES = 1024 * 1024 * 1024
SUPPORTED_CATEGORIES = {"DATABASE", "DOCUMENTS"}


def verify_restore_evidence(
    root,
    operation_id,
    expected_hash,
    expected_size,
    plan_id,
    expected_document,
    expected_document_hash,
    expected_document_size,
):
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
    objects = operation / "objects"
    objects_info = objects.lstat()
    if not stat.S_ISDIR(objects_info.st_mode) or getattr(objects_info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Invalid restore evidence directory")
    key = base64.b64decode(os.environ["JAP_MASTER_KEY"], validate=True)
    if len(key) != 32:
        raise ValueError("Invalid restore evidence key")

    def decrypt(path, context, maximum):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
            raise ValueError("Invalid restore evidence file")
        if getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Invalid restore evidence file")
        with path.open("rb") as stream:
            encoded = stream.read(maximum + 1)
        if len(encoded) > maximum:
            raise ValueError("Invalid restore evidence file")
        parts = encoded.decode("ascii").split(":", 3)
        if len(parts) != 4 or parts[:3] != ["jap", "v1", "local-v1"]:
            raise ValueError("Invalid restore evidence envelope")
        payload = base64.urlsafe_b64decode(parts[3].encode("ascii"))
        if len(payload) < 28:
            raise ValueError("Invalid restore evidence envelope")
        return AESGCM(key).decrypt(payload[:12], payload[12:], context.encode())

    def record(name, kind):
        value = json.loads(
            decrypt(
                operation / name,
                f"restore:v2:{operation_id}:{kind}",
                4 * 1024 * 1024,
            )
        )
        if not isinstance(value, dict):
            raise ValueError("Invalid restore evidence record")
        return value

    def target_path(value):
        if not isinstance(value, str) or len(value) > 512 or "\\" in value:
            raise ValueError("Invalid restore target")
        relative = PurePosixPath(value)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError("Invalid restore target")
        path = root.joinpath(*relative.parts)
        resolved = path.resolve(strict=True)
        if resolved == root or root not in resolved.parents:
            raise ValueError("Restore target is outside the smoke workspace")
        return path

    referenced_objects = set()

    def image_metadata(path_value, side, image):
        if not isinstance(image, dict) or set(image) != {"name", "sha256", "size"}:
            raise ValueError("Invalid restore image")
        expected_name = f"{hashlib.sha256(path_value.encode()).hexdigest()}.{side}.enc"
        if image["name"] != expected_name or not re.fullmatch(r"[a-f0-9]{64}", image["sha256"]):
            raise ValueError("Invalid restore image")
        if type(image["size"]) is not int or not 0 <= image["size"] <= MAX_FILE_BYTES:
            raise ValueError("Invalid restore image")

    def image_identity(path_value, side, image):
        image_metadata(path_value, side, image)
        if image["name"] in referenced_objects:
            raise ValueError("Restore image is referenced more than once")
        referenced_objects.add(image["name"])
        value = decrypt(
            objects / image["name"],
            f"restore:v2:{operation_id}:object:{image['name']}",
            512 * 1024 * 1024 + 4096,
        )
        if len(value) != image["size"] or hashlib.sha256(value).hexdigest() != image["sha256"]:
            raise ValueError("Restore image authentication failed")
        del value
        return image["sha256"], image["size"]

    def live_identity(path):
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or getattr(info, "st_file_attributes", 0) & 0x400
            or info.st_size > MAX_FILE_BYTES
        ):
            raise ValueError("Invalid committed restore target")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                size += len(block)
                if size > MAX_FILE_BYTES:
                    raise ValueError("Committed restore target exceeds its bound")
                digest.update(block)
        if size != info.st_size:
            raise ValueError("Committed restore target changed during verification")
        return digest.hexdigest(), size

    intent = record("intent.v2.enc", "intent")
    receipt = record("receipt.v2.enc", "receipt")
    if set(intent) != {
        "version",
        "policy",
        "operation_id",
        "workspace",
        "source",
        "applied_plan",
        "targets",
    } or set(receipt) != {"version", "intent_sha256", "outcome", "targets"}:
        raise ValueError("Restore record shape changed")
    source = intent.get("source")
    applied_plan = intent.get("applied_plan")
    if not isinstance(source, dict) or not isinstance(applied_plan, dict):
        raise ValueError("Restore evidence has invalid source records")
    if set(source) != {
        "version",
        "workspace",
        "database",
        "documents",
        "staged",
        "plan",
        "manifest",
        "inputs",
    }:
        raise ValueError("Restore source shape changed")
    source_plan = source.get("plan")
    manifest = source.get("manifest")
    if not isinstance(source_plan, dict) or not isinstance(manifest, dict):
        raise ValueError("Restore source plan is invalid")
    plan_categories = source_plan.get("categories")
    manifest_categories = manifest.get("categories")
    if (
        type(source.get("version")) is not int
        or source.get("version") != 1
        or not isinstance(plan_categories, list)
        or not plan_categories
        or any(
            type(category) is not str or category not in SUPPORTED_CATEGORIES
            for category in plan_categories
        )
        or len(set(plan_categories)) != len(plan_categories)
        or not isinstance(manifest_categories, list)
        or any(
            type(category) is not str or category not in SUPPORTED_CATEGORIES
            for category in manifest_categories
        )
        or len(set(manifest_categories)) != len(manifest_categories)
        or source_plan.get("backup_id") != manifest.get("id")
        or not set(plan_categories).issubset(manifest_categories)
    ):
        raise ValueError("Restore source no longer matches its reviewed manifest")
    if (
        type(intent.get("version")) is not int
        or intent.get("version") != 2
        or intent.get("policy") != "interrupted-restore-rollback/2"
        or intent.get("operation_id") != operation_id
        or type(receipt.get("version")) is not int
        or receipt.get("version") != 2
        or receipt.get("outcome") != "APPLIED"
        or source_plan.get("id") != plan_id
        or applied_plan.get("id") != plan_id
        or source_plan.get("status") != "STAGED"
        or applied_plan.get("status") != "APPLIED"
    ):
        raise ValueError("Restore evidence does not match the reviewed plan")
    if (
        Path(intent["workspace"]).resolve(strict=True) != root
        or Path(source.get("workspace", "")).resolve(strict=True) != root
    ):
        raise ValueError("Restore evidence belongs to another workspace")
    source_comparable = dict(source_plan)
    applied_comparable = dict(applied_plan)
    for value in (source_comparable, applied_comparable):
        value.pop("status", None)
        value.pop("applied_at", None)
    if source_comparable != applied_comparable:
        raise ValueError("Applied restore plan changed from the reviewed source plan")
    intent["source"]["plan"]["categories"] = sorted(intent["source"]["plan"]["categories"])
    intent["source"]["manifest"]["categories"] = sorted(
        intent["source"]["manifest"]["categories"]
    )
    intent["applied_plan"]["categories"] = sorted(intent["applied_plan"]["categories"])
    canonical = json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != receipt["intent_sha256"]:
        raise ValueError("Restore receipt does not authenticate its intent")
    targets = intent.get("targets")
    if not isinstance(targets, list) or not targets or len(targets) > 4097:
        raise ValueError("Invalid restore target inventory")
    paths = [target.get("path") for target in targets if isinstance(target, dict)]
    if (
        len(paths) != len(targets)
        or any(not isinstance(path, str) for path in paths)
        or len({path.casefold() for path in paths}) != len(paths)
    ):
        raise ValueError("Invalid restore target inventory")
    inputs = source.get("inputs")
    database_name = source.get("database")
    documents_name = source.get("documents")
    if (
        not isinstance(inputs, list)
        or not isinstance(database_name, str)
        or not isinstance(documents_name, str)
        or len(inputs) > 4096
        or type(source_plan.get("file_count")) is not int
        or source_plan.get("file_count") != len(inputs)
    ):
        raise ValueError("Invalid restore source inventory")
    source_total = 0
    input_paths = []
    database_inputs = 0
    for item in inputs:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
            raise ValueError("Invalid restore source input")
        item_path = item["path"]
        if (
            not isinstance(item_path, str)
            or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
            or type(item["size"]) is not int
            or not 0 <= item["size"] <= MAX_FILE_BYTES
        ):
            raise ValueError("Invalid restore source input")
        input_paths.append(item_path)
        source_total += item["size"]
        database_inputs += int(item_path == "database/job_apply_pro.db")
    if source_total > MAX_RESTORE_BYTES:
        raise ValueError("Restore source exceeds the supported 1 GiB bound")
    if len({path.casefold() for path in input_paths}) != len(input_paths):
        raise ValueError("Restore source contains case-colliding inputs")
    if database_inputs != int("DATABASE" in plan_categories):
        raise ValueError("Restore database input does not match its reviewed category")
    expected_paths = []
    expected_document_after = {}
    for item in inputs:
        item_path = item["path"]
        if item_path == "database/job_apply_pro.db":
            continue
        relative = PurePosixPath(item_path)
        if (
            "DOCUMENTS" not in plan_categories
            or len(relative.parts) < 2
            or relative.parts[0] != "documents"
        ):
            raise ValueError("Invalid restore document input")
        destination = PurePosixPath(documents_name).joinpath(*relative.parts[1:]).as_posix()
        target_path(destination)
        expected_paths.append(destination)
        expected_document_after[destination] = (item["sha256"], item["size"])
    expected_paths.append(database_name)
    if paths != expected_paths:
        raise ValueError("Restore target order changed from its source inputs")
    image_totals = {"before": 0, "after": 0}
    for target in targets:
        if not isinstance(target, dict) or set(target) != {"path", "before", "after"}:
            raise ValueError("Invalid restore target inventory")
        for side in ("before", "after"):
            image = target[side]
            if side == "before" and image is None:
                continue
            image_metadata(target["path"], side, image)
            image_totals[side] += image["size"]
    if any(total > MAX_RESTORE_BYTES for total in image_totals.values()):
        raise ValueError("Restore images exceed the supported 1 GiB per side bound")
    receipt_targets = receipt.get("targets")
    if not isinstance(receipt_targets, list) or len(receipt_targets) > 4097:
        raise ValueError("Invalid restore receipt inventory")
    for target in receipt_targets:
        if (
            not isinstance(target, list)
            or len(target) != 3
            or not isinstance(target[0], str)
            or not isinstance(target[1], str)
            or not re.fullmatch(r"[a-f0-9]{64}", target[1])
            or type(target[2]) is not int
            or not 0 <= target[2] <= MAX_FILE_BYTES
        ):
            raise ValueError("Invalid restore receipt inventory")
    expected_receipt = []
    images = {}
    for target in targets:
        path_value = target["path"]
        live_path = target_path(path_value)
        before = target["before"]
        images[(path_value, "before")] = (
            None if before is None else image_identity(path_value, "before", before)
        )
        after_identity = image_identity(path_value, "after", target["after"])
        images[(path_value, "after")] = after_identity
        if path_value != database_name and expected_document_after.get(path_value) != after_identity:
            raise ValueError("Restore document postimage changed from its source input")
        expected_receipt.append(
            [path_value, target["after"]["sha256"], target["after"]["size"]]
        )
        if live_identity(live_path) != after_identity:
            raise ValueError("Committed restore target no longer matches its receipt")
    if receipt_targets != expected_receipt:
        raise ValueError("Restore receipt target inventory changed")
    database_targets = [target for target in targets if target["path"] == database_name]
    if len(database_targets) != 1 or targets[-1] is not database_targets[0]:
        raise ValueError("Restore receipt does not identify the committed database")
    previous = images[(database_name, "before")]
    if previous != (expected_hash.lower(), int(expected_size)):
        raise ValueError("Previous database was not preserved exactly")
    if images.get((expected_document, "before")) != (
        expected_document_hash.lower(),
        int(expected_document_size),
    ):
        raise ValueError("Previous document was not preserved exactly")
    if {entry.name for entry in operation.iterdir()} != {
        "intent.v2.enc",
        "receipt.v2.enc",
        "objects",
    }:
        raise ValueError("Restore operation contains undocumented evidence")
    object_entries = list(objects.iterdir())
    if (
        len(object_entries) != len(referenced_objects)
        or {entry.name for entry in object_entries} != referenced_objects
    ):
        raise ValueError("Restore object inventory differs from authenticated intent")


if __name__ == "__main__":
    try:
        verify_restore_evidence(*sys.argv[1:])
    except Exception:
        print("Packaged durable restore evidence verification failed.", file=sys.stderr)
        raise SystemExit(1) from None
'@

$process = $null
$apiWorkerProcess = $null
$primarySmokeFailure = $null
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
    # Discovery is present in the frozen router, but all these requests stop
    # before public transport: invalid tokens/IDs or a nonexistent local profile.
    $discoveryCases = @(
        @{ path = "list"; body = @{ board_token = "internal" }; status = 422; detail = "Request validation failed; check required fields and supported values" },
        @{ path = "review"; body = @{ board_token = "package-smoke-no-network"; posting_id = "0" }; status = 422; detail = "Request validation failed; check required fields and supported values" },
        @{ path = "import"; body = @{ board_token = "package-smoke-no-network"; posting_id = "1"; review_fingerprint = ("a" * 64); profile_id = "package-smoke-missing-profile" }; status = 409; detail = "Local import conflicted; select an existing profile and refresh" }
    )
    foreach ($discoveryCase in $discoveryCases) {
        try {
            Invoke-RestMethod -Method Post -Uri "$apiRoot/api/v1/discovery/greenhouse/$($discoveryCase.path)" -Headers $headers -ContentType "application/json" -Body ($discoveryCase.body | ConvertTo-Json) -TimeoutSec 5 | Out-Null
            throw "Packaged invalid discovery request unexpectedly succeeded"
        }
        catch {
            if ($null -eq $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne $discoveryCase.status) { throw }
            $discoveryError = $_.ErrorDetails.Message | ConvertFrom-Json
            if ($discoveryError.detail -ne $discoveryCase.detail) { throw "Packaged discovery admission returned an unexpected error" }
        }
    }
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
    $originalMailDrafts = @(Invoke-RestMethod -Uri "$apiRoot/api/v1/communications/drafts" -Headers $headers -TimeoutSec 5 | ForEach-Object { $_ })
    if ($originalMailDrafts.Count -ne 2) { throw "Packaged offline mail previews are incomplete" }
    # Verify the frozen readiness routes without fetching a real board or
    # manufacturing a trusted public source. Simulator jobs cannot qualify.
    $readinessWorkflow = $originalMailDrafts[0].workflow_id
    if ($readinessWorkflow -notmatch '^mock-[a-f0-9-]{36}$' -or $originalMailDrafts[1].workflow_id -ne $readinessWorkflow) { throw "Packaged mail workflow identity changed" }
    $syntheticWorkflow = Invoke-RestMethod -Uri "$apiRoot/api/v1/workbench/workflows/$readinessWorkflow" -Headers $headers -TimeoutSec 5
    $readinessApplication = $syntheticWorkflow.application_id
    if ($readinessApplication -notmatch '^[a-zA-Z0-9_-]{1,100}$') { throw "Packaged readiness application identity is invalid" }
    $readinessUrl = "$apiRoot/api/v1/applications/$readinessApplication/job-review"
    $originalReadiness = Invoke-RestMethod -Uri $readinessUrl -Headers $headers -TimeoutSec 5
    if ($originalReadiness.supported -ne $false -or $originalReadiness.status -ne "UNSUPPORTED" -or @($originalReadiness.allowed_actions).Count -ne 0 -or $null -ne $originalReadiness.source) {
        throw "Packaged simulator workflow unexpectedly gained real-job readiness authority"
    }
    $unsupportedReadinessBody = @{ application_id = $readinessApplication; source_fingerprint = ("a" * 64); items = @() } | ConvertTo-Json
    try {
        Invoke-RestMethod -Method Post -Uri "$readinessUrl/requirements/preview" -Headers $headers -ContentType "application/json" -Body $unsupportedReadinessBody -TimeoutSec 5 | Out-Null
        throw "Packaged simulator requirements preview unexpectedly succeeded"
    }
    catch {
        if ($null -eq $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 409) { throw }
        $readinessError = $_.ErrorDetails.Message | ConvertFrom-Json
        if ($readinessError.detail -ne "Only saved public Greenhouse jobs before portal execution support this local review") { throw "Packaged readiness admission returned an unexpected error" }
    }
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
    $previousDocumentHash = (Get-FileHash -LiteralPath $documentPath -Algorithm SHA256).Hash
    $previousDocumentSize = (Get-Item -LiteralPath $documentPath).Length
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
    # Windows PowerShell's native -c argument rewriting can strip Python quotes.
    # Source travels over stdin; only the bounded synthetic values are arguments.
    $restoreEvidenceScript | & $PythonPath - $resolvedTestRoot $freshRestoreOperations[0].Name $previousDatabaseHash $previousDatabaseSize $plan.id "documents/restore-smoke.enc" $previousDocumentHash $previousDocumentSize
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
    # Offline previews have no provider identity and cannot reserve/send mail.
    # Verify their exact encrypted round-trip after restore without manufacturing
    # fake provider attempts just to preserve an older smoke expectation.
    $restoredMailAudits = @(Invoke-RestMethod -Uri "$apiRoot/api/v1/communications/mutation-audits" -Headers $headers -TimeoutSec 5 | ForEach-Object { $_ })
    if ($restoredMailAudits.Count -ne 0) { throw "Offline mail previews unexpectedly recorded provider attempts" }
    $restoredMailDrafts = @(Invoke-RestMethod -Uri "$apiRoot/api/v1/communications/drafts" -Headers $headers -TimeoutSec 5 | ForEach-Object { $_ })
    if ($restoredMailDrafts.Count -ne $originalMailDrafts.Count) { throw "Restored mail preview inventory changed" }
    foreach ($originalMailDraft in $originalMailDrafts) {
        $restoredMailDraft = Invoke-RestMethod -Uri "$apiRoot/api/v1/communications/drafts/$($originalMailDraft.id)" -Headers $headers -TimeoutSec 5
        if (($restoredMailDraft | ConvertTo-Json -Depth 30 -Compress) -ne ($originalMailDraft | ConvertTo-Json -Depth 30 -Compress)) {
            throw "Restored offline mail preview changed"
        }
        $mailReplayBody = @{
            fingerprint = $originalMailDraft.fingerprint
            idempotency_key = "post-restore-offline-" + [guid]::NewGuid().ToString("N")
            confirmed_by = "synthetic-package-probe"
        } | ConvertTo-Json
        try {
            Invoke-RestMethod -Method Post -Uri "$apiRoot/api/v1/communications/drafts/$($originalMailDraft.id)/send" -Headers $headers -ContentType "application/json" -Body $mailReplayBody -TimeoutSec 5 | Out-Null
            throw "Restored unbound mail preview unexpectedly allowed sending"
        }
        catch {
            if ($null -eq $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 409) { throw }
        }
    }
    $postRestoreMailAudits = @(Invoke-RestMethod -Uri "$apiRoot/api/v1/communications/mutation-audits" -Headers $headers -TimeoutSec 5 | ForEach-Object { $_ })
    if ($postRestoreMailAudits.Count -ne 0) { throw "Restored unbound previews created provider audit attempts" }
    $restoredReadiness = Invoke-RestMethod -Uri $readinessUrl -Headers $headers -TimeoutSec 5
    if (($restoredReadiness | ConvertTo-Json -Depth 30 -Compress) -ne ($originalReadiness | ConvertTo-Json -Depth 30 -Compress)) {
        throw "Restored simulator workflow changed its real-job readiness authority"
    }
    Write-Output "Packaged startup, migration, image decoding/rejection, cleanup API, loopback browser/worker lifecycle, verified mail attachment review, conservative job-readiness admission, encrypted backup and offline restore smoke passed."
}
catch {
    # Functional verification failures also need their logs and recovery evidence,
    # even when every captured process subsequently exits successfully.
    $script:smokePreserveArtifacts = $true
    $primarySmokeFailure = $_
    throw
}
finally {
    try {
        Stop-SmokeBackend -Process $process -WorkerProcess $apiWorkerProcess
    }
    catch { $script:smokePreserveArtifacts = $true }
    try { Complete-SmokeCleanup -Directory $resolvedTestRoot }
    catch {
        if ($null -eq $primarySmokeFailure) { throw }
        # Keep the original verification exception; cleanup's preservation error
        # must not hide which synthetic assertion failed. Evidence stays retained.
    }
}
