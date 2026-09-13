# ADR-0064: Bounded backend lifecycle

## Status and scope

Accepted for Bounded Backend Lifecycle `v0.54.0-alpha.1`. ADR-0063 fixed packaged browser execution; this release owns desktop migration, service and offline-restore process transitions. The previous supervisor could launch overlapping migrations, report stopped before child exit, accept stale readiness, and allow unsafe restore/restart overlap. This decision does not make multi-file restore atomic or establish Windows process-tree containment.

## Process ownership and admission

`BackendSupervisor` tracks every launched child in an `OwnedChild` record and an `owned` set. Records bind child kind, generation, exact process object, exit result, exit/failure promises and termination ownership. `serving` identifies the current API child. A successful `kill()` return is not exit proof; failed termination retains ownership and blocks restart/restore. A creation error with no PID establishes that no process was created; errors after creation do not prove exit.

`start()` coalesces callers through one published operation slot. Slots are assigned before status listeners run because listeners can synchronously reenter the supervisor. Every transition receives a new generation and `AbortController`; stale completions cannot publish ready state, launch another stage or revive a scheduler. `stop()` invalidates the generation, cancels readiness/scheduler requests and coalesces termination. `shutdown()` also closes admission to new backend work for the remainder of the app session.

`trackOperation()` publishes the starting/stopping/restoring promise before calling its operation and clears only that same promise on completion. `launch()` captures process-specific exit/error listeners; `waitForChild()` races exit, permitted failure/cancellation and an observation timer, then removes its timer and abort listener. `terminate()` coalesces cleanup for the same child and sets `stopRequested` so deliberate shutdown is not reported as an unexpected crash. `terminateOwned()` retains the exact child until its exit is observed or both observation periods expire. A synchronous listener can request another transition, so ownership is rechecked after publishing status and immediately before restore launch.

`BACKEND_LIFECYCLE_LIMITS` declares migration 60,000 ms, readiness 20,000 ms, readiness poll 250 ms, initial stop observation 5,000 ms, forced-stop observation 2,000 ms, and restore observation 120,000 ms. Migration and service processes may be terminated using their captured child objects. Stop requires observed exit; unconfirmed exit produces a static degraded message and leaves ownership intact. These are bounded observation policies, not guaranteed hard OS scheduling or process-tree deadlines.

## Readiness and scheduled work

Readiness uses a monotonic `performance.now()` deadline. Each authenticated runtime-status request receives the remaining budget and the generation's abort signal. Success is checked again against time, current generation and exact serving child before publishing ready. Source mode still launches the configured development interpreter; packaged mode uses the explicit bundled executable.

`BackendClient.request()` combines the caller's signal and a managed timeout with `AbortSignal.any()`, retaining the timeout while the response body is read and clearing its timer in `finally`. `runtimeStatus()` accepts the remaining-time override; `runDueBackupSchedules()` accepts the lifecycle signal. Cancellation prevents stale desktop continuations but does not prove the HTTP server cancelled work already accepted.

The backup scheduler captures the current generation, controller and serving child. It runs at most one request at a time, starts only in ready state, and rechecks ownership on every tick. Stop, replacement and unexpected service exit stop future scheduling. Its cancellation is not a transaction rollback guarantee for an already-started backup.

## Offline restore is not safely cancellable

`applyOfflineRestore()` owns one exclusive restore operation. It first proves prior child exit, then checks cancellation again immediately before launching the writer. Concurrent restore/start is rejected. The worker applies multiple filesystem changes, so timeout or desktop shutdown must never kill it. After 120 seconds without verified success, observation returns a recovery-required failure while the child remains owned.

An unfinished restore blocks quit, update and restart. After the writer exits, deliberate quit is permitted, but a nonzero, timed-out or uncertain restore outcome keeps automatic restart blocked. `prepareUpdate()` additionally rejects a recovery-required outcome even after writer exit because the installer would automatically relaunch the application. A normal within-budget exit code zero permits controlled backend restart; cancelled restart is reported explicitly.

`restoreRecoveryRequired` is a session-local guard, not a durable restore transaction marker. Do not delete staging files, force-close a surviving writer or reopen a partially restored workspace as if success were established. Durable crash/relaunch recovery journaling and atomic multi-file replacement remain separate source work.

## Desktop callers

The Electron entrypoint acquires the single-instance lock before encryption-key initialization or backend creation. A second instance only focuses the existing window. Early quit is tracked across asynchronous initialization so it cannot start a backend later.

`before-quit` prevents immediate exit and awaits terminal supervisor shutdown. A verified stop authorizes a second quit event; failure keeps or recreates a visible window and displays the sanitized recovery status. Notification polling stops before deliberate quit shutdown. Update installation coalesces callers and waits for its update-specific preparation gate before stopping notifications and invoking `quitAndInstall`; rejected preparation leaves ongoing notification polling intact. Failure is reported without invoking the installer. The renderer remains sandboxed and no privileged API is added.

## Verification and remaining evidence

Fake-child/fake-timer tests cover concurrent start, stop during migration/readiness, spawn errors, signal/nonzero exits, kill without exit, old-child events, synchronous listener reentrancy, scheduler cancellation, exclusive restore, timeout and late exit. Client tests cover caller cancellation, remaining timeout and response-body timer cleanup. Desktop/updater tests cover single-instance initialization, early quit, awaited shutdown, blocked quit/update and coalesced installation. The readiness audit records final exact-snapshot totals and packaged evidence; passing mocks alone does not prove physical Windows failures or signed update/rollback behavior.

`backend-supervisor.packaged.test.ts` is an explicit Windows opt-in through `JAP_LIFECYCLE_TEST_BACKEND`. It runs the current source supervisor against the exact delivered backend, captures real spawn handles without substituting process behavior, proves one migration/server pair for concurrent starts, authenticates readiness and build identity, waits for stop, then repeats a complete restart/stop cycle. It clears inherited application configuration and uses an empty temporary working directory, random credentials and a loopback port. Cleanup removes only its verified temporary directory after every captured child exits; uncertainty preserves the directory. Default unit runs report the test skipped; CI and release workflows opt in after packaging. This is real process evidence for the source supervisor and delivered backend, not a physical Electron-window, restore-failure or signed-installer rehearsal.
