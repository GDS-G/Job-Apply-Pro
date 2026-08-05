import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

import type { BackendRuntimeStatus } from "@job-apply-pro/contracts";

import { BackendClient } from "./backend-client.js";

type StatusListener = (status: BackendRuntimeStatus) => void;

export interface BackendSupervisorOptions {
  projectRoot: string;
  baseUrl: string;
  apiToken: string;
  masterKey: string;
  databaseUrl: string;
  pythonPath?: string;
}

export class BackendSupervisor {
  private child: ChildProcess | null = null;
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
    const pythonPath = this.options.pythonPath ?? this.resolvePython();
    const environment = {
      ...process.env,
      JAP_API_TOKEN: this.options.apiToken,
      JAP_MASTER_KEY: this.options.masterKey,
      JAP_DATABASE_URL: this.options.databaseUrl,
      PYTHONUNBUFFERED: "1",
    };

    const migrationExit = await this.runToCompletion(
      pythonPath,
      ["-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
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
      pythonPath,
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
    this.child?.kill();
    this.child = null;
    this.update("stopped", "Local backend stopped.");
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
