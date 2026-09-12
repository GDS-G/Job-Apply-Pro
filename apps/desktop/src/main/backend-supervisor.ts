import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

import type { BackendRuntimeStatus } from "@job-apply-pro/contracts";

import { BackendClient } from "./backend-client.js";

type StatusListener = (status: BackendRuntimeStatus) => void;
type ChildKind = "migration" | "serve" | "restore";
type ExitResult = { code: number | null; signal: NodeJS.Signals | null };
type WaitResult = ExitResult | "timeout" | "cancelled" | "error";
interface OwnedChild {
  child: ChildProcess;
  kind: ChildKind;
  generation: number;
  result: ExitResult | null;
  exited: Promise<ExitResult>;
  failed: Promise<"error">;
  stopRequested: boolean;
  termination: Promise<void> | null;
}

export const BACKEND_LIFECYCLE_LIMITS = {
  migrationMs: 60_000,
  readinessMs: 20_000,
  readinessPollMs: 250,
  stopMs: 5_000,
  forceStopMs: 2_000,
  restoreObservationMs: 120_000,
} as const;

const RESTORE_RECOVERY_REQUIRED =
  "Offline restore did not finish with a verified success. Data may be partially changed. Automatic restart is blocked for this app session; preserve backups and staging files and seek recovery guidance before reopening the workspace.";
const RESTORE_STILL_RUNNING =
  "Offline restore may still be writing data. Keep this app open until its process exits; restart, update, and quit are blocked. Do not delete staging files or force-close the app.";
const STOP_UNCONFIRMED =
  "The local backend has not confirmed exit. Restart, restore, and quit are blocked; keep the app open and retry shutdown after checking the owned process.";

export interface BackendSupervisorOptions {
  projectRoot: string;
  dataRoot: string;
  baseUrl: string;
  apiToken: string;
  masterKey: string;
  databaseUrl: string;
  backendExecutable?: string;
  browserEngine?: "chromium" | "chrome" | "msedge";
  pythonPath?: string;
}

export class BackendSupervisor {
  private owned = new Set<OwnedChild>();
  private serving: OwnedChild | null = null;
  private generation = 0;
  private controller: AbortController | null = null;
  private starting: Promise<void> | null = null;
  private stopping: Promise<void> | null = null;
  private restoring: Promise<void> | null = null;
  private closing = false;
  // Session-local guard, not a durable restore transaction marker.
  private restoreRecoveryRequired = false;
  private backupScheduleTimer: ReturnType<typeof setInterval> | null = null;
  private listeners = new Set<StatusListener>();
  private currentStatus: BackendRuntimeStatus = {
    state: "stopped",
    message: "Local backend has not started.",
    checked_at: new Date().toISOString(),
  };

  readonly client: BackendClient;

  constructor(private readonly options: BackendSupervisorOptions) {
    this.client = new BackendClient(options.baseUrl, options.apiToken);
  }

  get status(): BackendRuntimeStatus {
    return this.currentStatus;
  }

  onStatus(listener: StatusListener): () => void {
    this.listeners.add(listener);
    listener(this.currentStatus);
    return () => this.listeners.delete(listener);
  }

  start(): Promise<void> {
    if (this.closing)
      return Promise.reject(
        new Error(
          "Desktop shutdown has begun; new backend operations are blocked.",
        ),
      );
    if (this.restoring !== null || this.restoreRecoveryRequired) {
      return Promise.reject(new Error(RESTORE_RECOVERY_REQUIRED));
    }
    if (this.stopping !== null)
      return Promise.reject(
        new Error("Backend shutdown is still in progress."),
      );
    if (this.starting !== null) return this.starting;
    if (this.serving !== null && this.currentStatus.state === "ready")
      return Promise.resolve();
    if (this.owned.size > 0) return Promise.reject(new Error(STOP_UNCONFIRMED));
    const generation = this.newGeneration();
    const controller = this.controller!;
    return this.trackOperation("starting", () =>
      this.runStartup(generation, controller),
    );
  }

  stop(): Promise<void> {
    // Invalidate even if a restore's internal shutdown is already in flight.
    this.generation += 1;
    this.controller?.abort();
    this.stopBackupScheduler();
    return this.ensureStopped();
  }

  shutdown(): Promise<void> {
    // Terminal admission gate persists even if an updater fails or exit is delayed.
    this.closing = true;
    return this.stop();
  }

  applyOfflineRestore(planId: string, fingerprint: string): Promise<void> {
    if (this.closing)
      return Promise.reject(
        new Error(
          "Desktop shutdown has begun; new backend operations are blocked.",
        ),
      );
    if (this.restoring !== null || this.restoreRecoveryRequired)
      return Promise.reject(new Error(RESTORE_RECOVERY_REQUIRED));
    if (this.starting !== null || this.stopping !== null) {
      return Promise.reject(
        new Error("Wait for backend startup or shutdown before restoring."),
      );
    }
    const generation = this.newGeneration();
    const controller = this.controller!;
    return this.trackOperation("restoring", () =>
      this.runRestore(planId, fingerprint, generation, controller),
    );
  }

  markDegraded(message: string): void {
    this.stopBackupScheduler();
    this.update("degraded", message);
  }

  private newGeneration(): number {
    this.controller?.abort();
    this.stopBackupScheduler();
    this.controller = new AbortController();
    return ++this.generation;
  }

  private isCurrent(generation: number, controller: AbortController): boolean {
    return generation === this.generation && !controller.signal.aborted;
  }

  private trackOperation(
    slot: "starting" | "stopping" | "restoring",
    run: () => Promise<void>,
  ): Promise<void> {
    let resolve!: () => void;
    let reject!: (error: unknown) => void;
    const completion = new Promise<void>((yes, no) => {
      resolve = yes;
      reject = no;
    });
    const operation = completion.finally(() => {
      if (this[slot] === operation) this[slot] = null;
    });
    // Publish exclusivity before any status listener can synchronously reenter.
    this[slot] = operation;
    void run().then(resolve, reject);
    return operation;
  }

  private async runStartup(
    generation: number,
    controller: AbortController,
  ): Promise<void> {
    this.update("starting", "Preparing the encrypted local workspace…");
    try {
      if (!this.isCurrent(generation, controller)) return;
      const migration = this.launch(
        "migration",
        generation,
        ["migrate"],
        ["-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
      );
      const result = await this.waitForChild(
        migration,
        BACKEND_LIFECYCLE_LIMITS.migrationMs,
        controller.signal,
      );
      if (!this.isCurrent(generation, controller)) return;
      if (typeof result === "string" || result.code !== 0) {
        await this.terminate(migration);
        if (!this.isCurrent(generation, controller)) return;
        throw new Error("Database migration did not complete successfully.");
      }
      if (!this.isCurrent(generation, controller)) return;
      const serving = this.launch(
        "serve",
        generation,
        ["serve"],
        [
          "-m",
          "uvicorn",
          "job_apply_pro.main:app",
          "--app-dir",
          "backend/src",
          "--host",
          "127.0.0.1",
          "--port",
          "8765",
        ],
      );
      this.serving = serving;
      await this.waitUntilReady(serving, generation, controller);
    } catch (error) {
      if (!this.isCurrent(generation, controller)) return;
      this.stopBackupScheduler();
      const message =
        error instanceof Error && error.message === STOP_UNCONFIRMED
          ? STOP_UNCONFIRMED
          : "Local backend startup failed or timed out. Open diagnostics before retrying.";
      this.update("degraded", message);
      throw new Error(message);
    }
  }

  private async waitUntilReady(
    serving: OwnedChild,
    generation: number,
    controller: AbortController,
  ): Promise<void> {
    const deadline = performance.now() + BACKEND_LIFECYCLE_LIMITS.readinessMs;
    while (this.isCurrent(generation, controller) && serving.result === null) {
      const remainingMs = deadline - performance.now();
      if (remainingMs <= 0) break;
      try {
        await this.client.runtimeStatus({
          signal: controller.signal,
          timeoutMs: remainingMs,
        });
        if (
          !this.isCurrent(generation, controller) ||
          serving.result !== null ||
          this.serving !== serving
        )
          return;
        if (performance.now() >= deadline) break;
        this.update("ready", "Encrypted local backend connected.");
        this.startBackupScheduler(generation, controller, serving);
        return;
      } catch {
        if (!this.isCurrent(generation, controller)) return;
        const waitMs = Math.min(
          BACKEND_LIFECYCLE_LIMITS.readinessPollMs,
          Math.max(0, deadline - performance.now()),
        );
        const result = await this.waitForChild(
          serving,
          waitMs,
          controller.signal,
        );
        if (result !== "timeout") break;
      }
    }
    if (!this.isCurrent(generation, controller)) return;
    await this.terminate(serving);
    if (this.isCurrent(generation, controller))
      throw new Error("Local backend did not become ready before the timeout.");
  }

  private startBackupScheduler(
    generation: number,
    controller: AbortController,
    serving: OwnedChild,
  ): void {
    if (
      this.backupScheduleTimer !== null ||
      !this.isCurrent(generation, controller) ||
      this.serving !== serving ||
      serving.result !== null ||
      this.currentStatus.state !== "ready"
    )
      return;
    let running = false;
    const runDue = () => {
      if (
        running ||
        !this.isCurrent(generation, controller) ||
        this.serving !== serving ||
        serving.result !== null ||
        this.currentStatus.state !== "ready"
      )
        return;
      running = true;
      void this.client
        .runDueBackupSchedules(controller.signal)
        .catch(() => undefined)
        .finally(() => {
          running = false;
        });
    };
    this.backupScheduleTimer = setInterval(runDue, 60_000);
    runDue();
  }

  private stopBackupScheduler(): void {
    if (this.backupScheduleTimer !== null) {
      clearInterval(this.backupScheduleTimer);
      this.backupScheduleTimer = null;
    }
  }

  private ensureStopped(): Promise<void> {
    if (this.stopping !== null) return this.stopping;
    return this.trackOperation("stopping", () => this.stopOwned());
  }

  private async stopOwned(): Promise<void> {
    this.stopBackupScheduler();
    if ([...this.owned].some((owner) => owner.kind === "restore")) {
      this.update("degraded", RESTORE_STILL_RUNNING);
      throw new Error(RESTORE_STILL_RUNNING);
    }
    try {
      await Promise.all([...this.owned].map((owner) => this.terminate(owner)));
      if (this.owned.size > 0) throw new Error(STOP_UNCONFIRMED);
      this.update(
        this.restoreRecoveryRequired ? "degraded" : "stopped",
        this.restoreRecoveryRequired
          ? RESTORE_RECOVERY_REQUIRED
          : "Local backend stopped.",
      );
    } catch {
      this.update("degraded", STOP_UNCONFIRMED);
      throw new Error(STOP_UNCONFIRMED);
    }
  }

  private terminate(owner: OwnedChild): Promise<void> {
    if (owner.result !== null) return Promise.resolve();
    if (owner.termination !== null) return owner.termination;
    // Only terminate captured owned migration/server children. Restore writes are not atomic.
    if (owner.kind === "restore")
      return Promise.reject(new Error(RESTORE_STILL_RUNNING));
    owner.stopRequested = true;
    const operation = this.terminateOwned(owner).finally(() => {
      if (owner.termination === operation) owner.termination = null;
    });
    owner.termination = operation;
    return operation;
  }

  private async terminateOwned(owner: OwnedChild): Promise<void> {
    try {
      owner.child.kill();
    } catch {
      /* Exit proof is still required. */
    }
    if (
      (await this.waitForChild(
        owner,
        BACKEND_LIFECYCLE_LIMITS.stopMs,
        undefined,
        true,
      )) !== "timeout"
    )
      return;
    try {
      owner.child.kill("SIGKILL");
    } catch {
      /* Keep ownership on failure. */
    }
    if (
      (await this.waitForChild(
        owner,
        BACKEND_LIFECYCLE_LIMITS.forceStopMs,
        undefined,
        true,
      )) !== "timeout"
    )
      return;
    throw new Error(STOP_UNCONFIRMED);
  }

  private async runRestore(
    planId: string,
    fingerprint: string,
    generation: number,
    controller: AbortController,
  ): Promise<void> {
    this.update(
      "starting",
      "Stopping the backend for verified offline restore…",
    );
    await this.ensureStopped();
    if (!this.isCurrent(generation, controller))
      throw new Error(
        "Offline restore was cancelled before any restore process was launched.",
      );
    this.update(
      "starting",
      "Applying verified offline restore; keep the app open…",
    );
    if (!this.isCurrent(generation, controller))
      throw new Error(
        "Offline restore was cancelled before any restore process was launched.",
      );
    let owner: OwnedChild;
    try {
      owner = this.launch(
        "restore",
        generation,
        ["restore", "--plan-id", planId, "--fingerprint", fingerprint],
        [
          "-m",
          "job_apply_pro.desktop_entry",
          "restore",
          "--plan-id",
          planId,
          "--fingerprint",
          fingerprint,
        ],
      );
    } catch {
      this.restoreRecoveryRequired = true;
      this.update("degraded", RESTORE_RECOVERY_REQUIRED);
      throw new Error(RESTORE_RECOVERY_REQUIRED);
    }
    // Observation is bounded; cancellation/timeout must NEVER kill this writer.
    const result = await this.waitForChild(
      owner,
      BACKEND_LIFECYCLE_LIMITS.restoreObservationMs,
    );
    if (typeof result === "string" || result.code !== 0) {
      this.restoreRecoveryRequired = true;
      const message =
        owner.result === null
          ? RESTORE_STILL_RUNNING
          : RESTORE_RECOVERY_REQUIRED;
      this.update("degraded", message);
      throw new Error(message);
    }
    if (!this.isCurrent(generation, controller)) {
      this.update(
        "stopped",
        "Offline restore completed; backend restart was cancelled.",
      );
      return;
    }
    await this.runStartup(generation, controller);
  }

  private launch(
    kind: ChildKind,
    generation: number,
    packagedArgs: string[],
    pythonArgs: string[],
  ): OwnedChild {
    let child: ChildProcess;
    try {
      child = spawn(
        this.options.backendExecutable ??
          this.options.pythonPath ??
          this.resolvePython(),
        this.options.backendExecutable ? packagedArgs : pythonArgs,
        {
          cwd: this.options.projectRoot,
          env: this.runtimeEnvironment(),
          windowsHide: true,
          stdio: "ignore",
        },
      );
    } catch {
      throw new Error("The local backend process could not be launched.");
    }
    let resolveExit!: (result: ExitResult) => void;
    let resolveFailure!: (result: "error") => void;
    const owner: OwnedChild = {
      child,
      kind,
      generation,
      result: null,
      stopRequested: false,
      termination: null,
      exited: new Promise((resolve) => {
        resolveExit = resolve;
      }),
      failed: new Promise((resolve) => {
        resolveFailure = resolve;
      }),
    };
    this.owned.add(owner);
    const completed = (code: number | null, signal: NodeJS.Signals | null) => {
      if (owner.result !== null) return;
      owner.result = { code, signal };
      this.owned.delete(owner);
      if (this.serving === owner) this.serving = null;
      resolveExit(owner.result);
      if (
        kind === "serve" &&
        generation === this.generation &&
        !owner.stopRequested
      ) {
        this.stopBackupScheduler();
        this.controller?.abort();
        this.update(
          "degraded",
          "Local backend exited unexpectedly. Open diagnostics before restarting.",
        );
      }
      if (kind === "restore" && this.restoreRecoveryRequired)
        this.update("degraded", RESTORE_RECOVERY_REQUIRED);
    };
    child.once("exit", completed);
    child.on("error", () => {
      if (owner.result !== null) return;
      resolveFailure("error");
      // Node supplies no PID when creation failed; later errors do not prove exit.
      if (child.pid === undefined) completed(null, null);
    });
    return owner;
  }

  private async waitForChild(
    owner: OwnedChild,
    timeoutMs: number,
    signal?: AbortSignal,
    exitOnly = false,
  ): Promise<WaitResult> {
    if (owner.result !== null) return owner.result;
    if (signal?.aborted) return "cancelled";
    let timer: ReturnType<typeof setTimeout> | undefined;
    let aborted: (() => void) | undefined;
    try {
      return await Promise.race([
        owner.exited,
        ...(exitOnly ? [] : [owner.failed]),
        new Promise<"timeout">((resolve) => {
          timer = setTimeout(() => resolve("timeout"), timeoutMs);
        }),
        new Promise<"cancelled">((resolve) => {
          aborted = () => resolve("cancelled");
          signal?.addEventListener("abort", aborted, { once: true });
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      if (aborted !== undefined) signal?.removeEventListener("abort", aborted);
    }
  }

  private runtimeEnvironment(): NodeJS.ProcessEnv {
    return {
      ...process.env,
      JAP_API_TOKEN: this.options.apiToken,
      JAP_MASTER_KEY: this.options.masterKey,
      JAP_DATABASE_URL: this.options.databaseUrl,
      JAP_BROWSER_DATA_DIR: join(this.options.dataRoot, "browser"),
      JAP_BROWSER_ARTIFACT_DIR: join(
        this.options.dataRoot,
        "browser-artifacts",
      ),
      JAP_DOCUMENT_DATA_DIR: join(this.options.dataRoot, "documents"),
      JAP_BACKUP_DATA_DIR: join(this.options.dataRoot, "backups"),
      JAP_RESTORE_STAGING_DIR: join(this.options.dataRoot, "restore-staging"),
      JAP_BROWSER_ENGINE: this.options.browserEngine ?? "chromium",
      PYTHONUNBUFFERED: "1",
    };
  }

  private resolvePython(): string {
    const candidates = [
      join(this.options.projectRoot, ".venv-dev", "Scripts", "python.exe"),
      join(this.options.projectRoot, ".venv", "Scripts", "python.exe"),
    ];
    return candidates.find((candidate) => existsSync(candidate)) ?? "python";
  }

  private update(state: BackendRuntimeStatus["state"], message: string): void {
    this.currentStatus = {
      state,
      message,
      checked_at: new Date().toISOString(),
    };
    for (const listener of this.listeners) listener(this.currentStatus);
  }
}
