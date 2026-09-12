# ADR-0063: Packaged browser runtime

## Status and reproduced defect

Accepted for Packaged Browser Runtime `v0.53.0-alpha.1`. The v0.52 frozen backend with SHA-256 `CF33280274A9D6BA1554D4B91A432A9BF9AE3AD7A53B78DE588B7231B2865F45` exits with code 2 and no JSON-lines shutdown response when invoked using the former `sys.executable -m job_apply_pro.browser.worker_process` command. In a frozen application, `sys.executable` is the backend EXE, not a Python command-line interpreter. Its windowed bootloader also does not provide the standard streams required by worker RPC. Existing source tests and packaged health/backup smoke did not exercise this path.

## Executables and entry dispatch

`backend/job_apply_pro_backend.spec` creates two executables in one onedir bundle. `job-apply-pro-backend.exe` remains windowed. `job-apply-pro-browser-worker.exe` is console-capable so that Python has stdin/stdout, but its parent launches it with `CREATE_NO_WINDOW` and redirected pipes. Both executables share the existing `Analysis`, `PYZ`, entry script and collected dependency/data tree. Electron Builder copies the entire directory to `resources/backend`; no system Python, separate dependency installation or downloaded worker is used in packaged operation.

`desktop_entry.py:main()` adds the explicit `browser-worker` command alongside `migrate`, `serve` and `restore`. It rejects restore-only arguments and missing standard streams for worker mode, then imports and dispatches `browser.worker_process.main`. API, database, migration and restore imports occur lazily in their respective functions, so worker startup does not initialize those subsystems. The static worker import also makes its modules visible to PyInstaller analysis. Migration, HTTP service and offline restore semantics remain unchanged.

## Client launch boundary

`browser/client.py:FROZEN_BROWSER_WORKER_NAME` fixes the filename. Frozen mode resolves only the sibling of the running backend executable, requires that file, removes inherited `PYTHONPATH`, sets the packaged directory as cwd, and invokes the explicit worker command. Missing worker or OS launch failure produces a controlled `BrowserWorkerUnavailableError`; it does not fall back to an arbitrary PATH interpreter. Source mode retains the existing `python -m` command and source-root Python path.

The client uses UTF-8 JSON-lines stdin/stdout, discarded stderr and hidden Windows launches. Each reader thread captures the exact process it owns rather than looking up a later replacement through `self._process`. Broken/closed pipe writes become controlled unavailable errors without reflecting OS/path details. Existing browser service gates still control workflow ownership, exact permitted origins, actions and confirmation evidence. No renderer privilege, production portal flag, external consent or final submission gate is weakened. The worker is a process boundary, not an OS sandbox against the same local user modifying installation files.

## Packaged acceptance

The package smoke uses isolated temporary storage and an in-memory fixture served only on loopback. It verifies the worker executable directly through start, observe, stop and shutdown RPC, then creates a synthetic candidate/workflow and browser session through the packaged authenticated API. The API path tests the actual `BrowserWorkerClient` sibling launch, not only a standalone executable. Expected page content, successful session closure and worker exit are checked without real portal accounts or external model providers. Source tests continue to exercise the development worker path.

The same smoke runs against both backend-dist and the backend copied into the unpacked Electron application through `test_packaged_backend.ps1 -BackendDirectory release/win-unpacked/resources/backend`. CI and the signed release workflow exercise the delivered copy before accepting or publishing an artifact. `generate_release_metadata.ps1` requires valid Authenticode for the installer and all three delivered application processes: desktop, backend and browser worker. Exact source commit, test totals, worker/backend/installer hashes, signature status and protected checks belong in the readiness audit; local unsigned smoke cannot be presented as signed or live-provider acceptance.

## Remaining lifecycle work

This decision repairs the frozen worker executable path. It does not establish whole-process-tree containment, physical sleep/network/storage recovery or a hard RPC cancellation guarantee. The desktop supervisor still needs coalesced startup, tracked/bounded migration, controlled serve spawn errors, stale-readiness fencing, awaited shutdown and exclusive restore ownership. Restore applies multiple filesystem changes; termination can leave a partial outcome, so it must not be treated like a safely cancellable migration or automatically restarted while a writer may remain alive. Those changes require a separate lifecycle release and tests.
