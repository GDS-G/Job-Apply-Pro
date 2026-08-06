import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

import type { BackendRuntimeStatus } from "@job-apply-pro/contracts";

import { BackendClient } from "./backend-client.js";

type StatusListener = (status: BackendRuntimeStatus) => void;

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
  private child: ChildProcess | null = null;
  private backupScheduleTimer: ReturnType<typeof setInterval> | null = null;
  private stopping = false;
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

  async start(): Promise<void> {
    if (this.child !== null) return;
    this.stopping = false;
    this.update("starting", "Preparing the encrypted local workspace…");
    const packagedBackend = this.options.backendExecutable;
    const executable =
      packagedBackend ?? this.options.pythonPath ?? this.resolvePython();
    const environment = this.runtimeEnvironment();

    const migrationExit = await this.runToCompletion(
      executable,
      packagedBackend
        ? ["migrate"]
        : ["-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
      environment,
    );
    if (migrationExit !== 0) {
      this.update(
        "degraded",
        "Database migration failed. Open diagnostics for details.",
      );
      return;
    }

    this.child = spawn(
      executable,
      packagedBackend
        ? ["serve"]
        : [
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
      {
        cwd: this.options.projectRoot,
        env: environment,
        windowsHide: true,
        stdio: "ignore",
      },
    );
    this.child.once("exit", (code) => {
      this.child = null;
      if (!this.stopping) {
        this.update(
          "degraded",
          `Local backend exited unexpectedly (${code ?? "unknown"}).`,
        );
      }
    });
    await this.waitUntilReady();
  }

  stop(): void {
    this.stopping = true;
    if (this.backupScheduleTimer !== null) {
      clearInterval(this.backupScheduleTimer);
      this.backupScheduleTimer = null;
    }
    this.child?.kill();
    this.update("stopped", "Local backend stopped.");
  }

  async applyOfflineRestore(
    planId: string,
    fingerprint: string,
  ): Promise<void> {
    this.update(
      "starting",
      "Stopping the backend for verified offline restore…",
    );
    await this.stopAndWait();
    const packagedBackend = this.options.backendExecutable;
    const executable =
      packagedBackend ?? this.options.pythonPath ?? this.resolvePython();
    const result = await this.runToCompletion(
      executable,
      packagedBackend
        ? ["restore", "--plan-id", planId, "--fingerprint", fingerprint]
        : [
            "-m",
            "job_apply_pro.desktop_entry",
            "restore",
            "--plan-id",
            planId,
            "--fingerprint",
            fingerprint,
          ],
      this.runtimeEnvironment(),
    );
    if (result !== 0) {
      await this.start();
      throw new Error(
        "The offline restore was rejected or failed. Existing data remains recoverable; export diagnostics before retrying.",
      );
    }
    await this.start();
  }

  markDegraded(message: string): void {
    this.update("degraded", message);
  }

  private async waitUntilReady(): Promise<void> {
    const deadline = Date.now() + 20_000;
    while (Date.now() < deadline && this.child !== null) {
      try {
        await this.client.runtimeStatus();
        this.update("ready", "Encrypted local backend connected.");
        this.startBackupScheduler();
        return;
      } catch {
        await delay(250);
      }
    }
    if (this.child !== null) {
      this.update(
        "degraded",
        "Local backend did not become ready before the timeout.",
      );
    }
  }

  private startBackupScheduler(): void {
    if (this.backupScheduleTimer !== null) return;
    const runDue = () => {
      void this.client.runDueBackupSchedules().catch(() => undefined);
    };
    runDue();
    this.backupScheduleTimer = setInterval(runDue, 60_000);
  }

  private async stopAndWait(): Promise<void> {
    const child = this.child;
    this.stop();
    if (child === null || child.exitCode !== null) return;
    const exited = await Promise.race([
      new Promise<boolean>((resolve) =>
        child.once("exit", () => resolve(true)),
      ),
      delay(5_000).then(() => false),
    ]);
    if (exited) return;
    child.kill("SIGKILL");
    const forceExited = await Promise.race([
      new Promise<boolean>((resolve) =>
        child.once("exit", () => resolve(true)),
      ),
      delay(2_000).then(() => false),
    ]);
    if (!forceExited && child.exitCode === null && child.signalCode === null) {
      this.update(
        "degraded",
        "The backend could not be stopped; restore was not attempted.",
      );
      throw new Error(
        "The local backend could not be stopped safely. Restore was not attempted.",
      );
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

  private runToCompletion(
    executable: string,
    args: string[],
    environment: NodeJS.ProcessEnv,
  ): Promise<number | null> {
    return new Promise((resolve, reject) => {
      const child = spawn(executable, args, {
        cwd: this.options.projectRoot,
        env: environment,
        windowsHide: true,
        stdio: "ignore",
      });
      child.once("error", reject);
      child.once("exit", resolve);
    });
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
