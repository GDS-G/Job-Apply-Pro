import { spawn, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BackendClient } from "./backend-client.js";
import {
  BackendSupervisor,
  BACKEND_LIFECYCLE_LIMITS,
} from "./backend-supervisor.js";

vi.mock("node:child_process", () => {
  const spawn = vi.fn();
  return { spawn, default: { spawn } };
});

class FakeChild extends EventEmitter {
  pid: number | undefined = 4100;
  exitCode: number | null = null;
  signalCode: NodeJS.Signals | null = null;
  kill = vi.fn((_signal?: NodeJS.Signals) => true);
  exit(code: number | null = 0, signal: NodeJS.Signals | null = null): void {
    this.exitCode = code;
    this.signalCode = signal;
    this.emit("exit", code, signal);
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

const options = {
  projectRoot: "C:/synthetic/project",
  dataRoot: "C:/synthetic/data",
  baseUrl: "http://127.0.0.1:8765/api/v1",
  apiToken: "synthetic-token",
  masterKey: "synthetic-key",
  databaseUrl: "sqlite:///synthetic.db",
  backendExecutable: "C:/synthetic/backend.exe",
};

describe("owned backend lifecycle", () => {
  let children: FakeChild[];
  let supervisor: BackendSupervisor;
  beforeEach(() => {
    vi.useFakeTimers();
    children = [];
    vi.mocked(spawn).mockImplementation(() => {
      const child = new FakeChild();
      children.push(child);
      return child as unknown as ChildProcess;
    });
    vi.spyOn(BackendClient.prototype, "runtimeStatus").mockResolvedValue();
    vi.spyOn(
      BackendClient.prototype,
      "runDueBackupSchedules",
    ).mockResolvedValue([]);
    supervisor = new BackendSupervisor(options);
  });
  afterEach(() => {
    vi.clearAllTimers();
    vi.restoreAllMocks();
    vi.mocked(spawn).mockReset();
    vi.useRealTimers();
  });

  async function ready(): Promise<FakeChild> {
    const starting = supervisor.start();
    children[0]!.exit();
    await starting;
    expect(supervisor.status.state).toBe("ready");
    return children[1]!;
  }

  it("coalesces concurrent start, launches hidden, and waits for migration", async () => {
    const first = supervisor.start();
    expect(supervisor.start()).toBe(first);
    expect(spawn).toHaveBeenCalledTimes(1);
    expect(vi.mocked(spawn).mock.calls[0]?.[1]).toEqual(["migrate"]);
    children[0]!.exit();
    await first;
    expect(spawn).toHaveBeenCalledTimes(2);
    expect(vi.mocked(spawn).mock.calls[1]?.[1]).toEqual(["serve"]);
    for (const call of vi.mocked(spawn).mock.calls) {
      expect(call[2]).toMatchObject({
        windowsHide: true,
        stdio: "ignore",
        cwd: options.projectRoot,
      });
    }
    expect(supervisor.client.runDueBackupSchedules).toHaveBeenCalledTimes(1);
    await supervisor.start();
    expect(spawn).toHaveBeenCalledTimes(2);
  });

  it("coalesces shutdown and reports stopped only after signal exit", async () => {
    const child = await ready();
    const first = supervisor.stop();
    expect(supervisor.stop()).toBe(first);
    expect(child.kill).toHaveBeenCalledTimes(1);
    expect(supervisor.status.state).not.toBe("stopped");
    child.exit(null, "SIGTERM");
    await first;
    expect(supervisor.status.state).toBe("stopped");
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(180_000);
    expect(supervisor.client.runDueBackupSchedules).toHaveBeenCalledTimes(1);
  });

  it("stops an owned migration without allowing a stale server spawn", async () => {
    const starting = supervisor.start();
    const stop = supervisor.stop();
    expect(children[0]!.kill).toHaveBeenCalledOnce();
    children[0]!.exit();
    await Promise.all([starting, stop]);
    expect(spawn).toHaveBeenCalledTimes(1);
    expect(supervisor.status.state).toBe("stopped");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not revive readiness or schedules after a cancelled stale request succeeds", async () => {
    const health = deferred<void>();
    vi.mocked(supervisor.client.runtimeStatus).mockReturnValue(health.promise);
    const starting = supervisor.start();
    children[0]!.exit();
    await vi.advanceTimersByTimeAsync(0);
    const request = vi.mocked(supervisor.client.runtimeStatus).mock
      .calls[0]![0]!;
    expect(request.timeoutMs).toBe(BACKEND_LIFECYCLE_LIMITS.readinessMs);
    const stop = supervisor.stop();
    expect(request.signal?.aborted).toBe(true);
    children[1]!.exit();
    await stop;
    health.resolve();
    await starting;
    expect(supervisor.status.state).toBe("stopped");
    expect(supervisor.client.runDueBackupSchedules).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("sanitizes synchronous spawn failures", async () => {
    vi.mocked(spawn).mockImplementationOnce(() => {
      throw new Error("C:/private/secret-token");
    });
    await expect(supervisor.start()).rejects.toThrow("startup failed");
    expect(supervisor.status.message).not.toContain("private");
    expect(supervisor.status.message).not.toContain("secret-token");
    await supervisor.stop();
    expect(supervisor.status.state).toBe("stopped");
  });

  it("handles asynchronous creation failure without leaking an unhandled error or owner", async () => {
    const result = supervisor.start().catch((error: unknown) => error);
    children[0]!.pid = undefined;
    children[0]!.emit("error", new Error("private-command-line"));
    expect(await result).toBeInstanceOf(Error);
    expect(supervisor.status.state).toBe("degraded");
    expect(supervisor.status.message).not.toContain("private");
    expect(children[0]!.kill).not.toHaveBeenCalled();
    await supervisor.stop();
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([1, null])(
    "never serves after non-successful migration (%s)",
    async (code) => {
      const result = supervisor.start().catch((error: unknown) => error);
      children[0]!.exit(code, code === null ? "SIGTERM" : null);
      expect(await result).toBeInstanceOf(Error);
      expect(spawn).toHaveBeenCalledOnce();
      expect(supervisor.status.state).toBe("degraded");
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it("bounds a hung migration and preserves ownership when kill is accepted without exit", async () => {
    const result = supervisor.start().catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(
      BACKEND_LIFECYCLE_LIMITS.migrationMs + 7_000,
    );
    expect(await result).toBeInstanceOf(Error);
    expect(children[0]!.kill.mock.calls).toEqual([[], ["SIGKILL"]]);
    expect(supervisor.status.message).toContain("not confirmed exit");
    await expect(supervisor.start()).rejects.toThrow("not confirmed exit");
    expect(spawn).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
    children[0]!.exit(null, "SIGKILL");
    await supervisor.stop();
    expect(supervisor.status.state).toBe("stopped");
  });

  it.each([false, "throw"])(
    "does not treat kill refusal (%s) as exit proof",
    async (result) => {
      const child = await ready();
      child.kill.mockImplementation(() => {
        if (result === "throw") throw new Error("private process error");
        return false;
      });
      const stop = supervisor.stop().catch((error: unknown) => error);
      await vi.advanceTimersByTimeAsync(7_000);
      expect(await stop).toBeInstanceOf(Error);
      expect(supervisor.status.state).toBe("degraded");
      expect(supervisor.status.message).not.toContain("private");
      await expect(supervisor.start()).rejects.toThrow("not confirmed exit");
      child.exit(null, "SIGTERM");
      await supervisor.stop();
      expect(supervisor.status.state).toBe("stopped");
    },
  );

  it("uses one readiness budget and stops an unready server", async () => {
    vi.mocked(supervisor.client.runtimeStatus).mockRejectedValue(
      new Error("synthetic offline"),
    );
    const result = supervisor.start().catch((error: unknown) => error);
    children[0]!.exit();
    await vi.advanceTimersByTimeAsync(0);
    children[1]!.kill.mockImplementation(() => {
      children[1]!.exit(null, "SIGTERM");
      return true;
    });
    await vi.advanceTimersByTimeAsync(20_000);
    await result;
    const calls = vi.mocked(supervisor.client.runtimeStatus).mock.calls;
    expect(calls[0]?.[0]?.timeoutMs).toBe(20_000);
    expect(calls.at(-1)?.[0]?.timeoutMs).toBeLessThanOrEqual(250);
    expect(supervisor.status.state).toBe("degraded");
    expect(supervisor.client.runDueBackupSchedules).not.toHaveBeenCalled();
    expect(children[1]!.kill).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not trust successful health after its deadline", async () => {
    const health = deferred<void>();
    vi.mocked(supervisor.client.runtimeStatus).mockReturnValue(health.promise);
    const starting = supervisor.start().catch((error: unknown) => error);
    children[0]!.exit();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(20_001);
    children[1]!.kill.mockImplementation(() => {
      children[1]!.exit(null, "SIGTERM");
      return true;
    });
    health.resolve();
    expect(await starting).toBeInstanceOf(Error);
    expect(supervisor.status.state).toBe("degraded");
    expect(supervisor.client.runDueBackupSchedules).not.toHaveBeenCalled();
  });

  it("handles a server spawn error and ignores stale health success", async () => {
    const health = deferred<void>();
    vi.mocked(supervisor.client.runtimeStatus).mockReturnValue(health.promise);
    const starting = supervisor.start();
    children[0]!.exit();
    await vi.advanceTimersByTimeAsync(0);
    children[1]!.pid = undefined;
    children[1]!.emit("error", new Error("private executable"));
    health.resolve();
    await starting;
    expect(supervisor.status.state).toBe("degraded");
    expect(supervisor.status.message).not.toContain("private");
    expect(supervisor.client.runDueBackupSchedules).not.toHaveBeenCalled();
    await supervisor.stop();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("an error on an already spawned child still requires exit proof", async () => {
    const starting = supervisor.start().catch((error: unknown) => error);
    children[0]!.emit("error", new Error("private runtime error"));
    await vi.advanceTimersByTimeAsync(7_000);
    expect(await starting).toBeInstanceOf(Error);
    await expect(supervisor.start()).rejects.toThrow("not confirmed exit");
    children[0]!.exit();
    await supervisor.stop();
  });

  it("old child events cannot clear a newer owner or degrade its status", async () => {
    const old = await ready();
    const stop = supervisor.stop();
    old.exit();
    await stop;
    const newStart = supervisor.start();
    children[2]!.exit();
    await newStart;
    old.emit("exit", 1, null);
    old.emit("error", new Error("stale"));
    expect(supervisor.status.state).toBe("ready");
    const finalStop = supervisor.stop();
    expect(children[3]!.kill).toHaveBeenCalledOnce();
    children[3]!.exit();
    await finalStop;
  });

  it("cancels the in-flight scheduler and never overlaps scheduled runs", async () => {
    const backup = deferred<never[]>();
    vi.mocked(supervisor.client.runDueBackupSchedules).mockReturnValue(
      backup.promise,
    );
    const child = await ready();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(supervisor.client.runDueBackupSchedules).toHaveBeenCalledOnce();
    const signal = vi.mocked(supervisor.client.runDueBackupSchedules).mock
      .calls[0]![0]!;
    const stop = supervisor.stop();
    expect(signal.aborted).toBe(true);
    child.exit();
    await stop;
    backup.resolve([]);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(supervisor.client.runDueBackupSchedules).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("rejects restore overlapping startup", async () => {
    const starting = supervisor.start();
    await expect(
      supervisor.applyOfflineRestore("synthetic-plan", "synthetic-hash"),
    ).rejects.toThrow("startup or shutdown");
    const stop = supervisor.stop();
    children[0]!.exit();
    await Promise.all([starting, stop]);
    expect(spawn).toHaveBeenCalledOnce();
  });

  it("requires exit before exclusive restore and restarts only on verified success", async () => {
    const child = await ready();
    const restore = supervisor.applyOfflineRestore(
      "synthetic-plan",
      "synthetic-hash",
    );
    await expect(
      supervisor.applyOfflineRestore("other", "other"),
    ).rejects.toThrow("Offline restore");
    await expect(supervisor.start()).rejects.toThrow("Offline restore");
    expect(spawn).toHaveBeenCalledTimes(2);
    child.exit();
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.mocked(spawn).mock.calls[2]?.[1]).toEqual([
      "restore",
      "--plan-id",
      "synthetic-plan",
      "--fingerprint",
      "synthetic-hash",
    ]);
    children[2]!.exit();
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.mocked(spawn).mock.calls[3]?.[1]).toEqual(["migrate"]);
    children[3]!.exit();
    await restore;
    expect(supervisor.status.state).toBe("ready");
    expect(spawn).toHaveBeenCalledTimes(5);
  });

  it("shutdown during restore preparation cancels the pending writer", async () => {
    const child = await ready();
    const restore = supervisor
      .applyOfflineRestore("synthetic-plan", "synthetic-hash")
      .catch((error: unknown) => error);
    const stop = supervisor.stop();
    child.exit();
    await stop;
    expect(await restore).toBeInstanceOf(Error);
    expect(spawn).toHaveBeenCalledTimes(2);
    expect(supervisor.status.state).toBe("stopped");
  });

  it("does not attempt restore when server exit is unproven", async () => {
    await ready();
    const restore = supervisor
      .applyOfflineRestore("synthetic-plan", "synthetic-hash")
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(7_000);
    expect(await restore).toBeInstanceOf(Error);
    expect(spawn).toHaveBeenCalledTimes(2);
    expect(supervisor.status.state).toBe("degraded");
  });

  it.each([1, null])(
    "keeps failed restore offline without claiming unchanged data (%s)",
    async (code) => {
      const restore = supervisor
        .applyOfflineRestore("synthetic-plan", "synthetic-hash")
        .catch((error: unknown) => error);
      await vi.advanceTimersByTimeAsync(0);
      children[0]!.exit(code, code === null ? "SIGTERM" : null);
      expect(await restore).toBeInstanceOf(Error);
      expect(spawn).toHaveBeenCalledOnce();
      expect(supervisor.status.message).toContain("partially changed");
      expect(supervisor.status.message).not.toContain("unchanged");
      await expect(supervisor.start()).rejects.toThrow("partially changed");
      await expect(
        supervisor.applyOfflineRestore("other", "other"),
      ).rejects.toThrow("partially changed");
      await supervisor.stop();
      expect(supervisor.status.state).toBe("degraded");
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it("does not kill a timed-out restore, preserves its owner, and refuses unsafe quit", async () => {
    const restore = supervisor
      .applyOfflineRestore("synthetic-plan", "synthetic-hash")
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(await restore).toBeInstanceOf(Error);
    expect(children[0]!.kill).not.toHaveBeenCalled();
    await expect(supervisor.stop()).rejects.toThrow("still be writing");
    await expect(supervisor.stop()).rejects.toThrow("still be writing");
    await expect(supervisor.start()).rejects.toThrow("partially changed");
    expect(children[0]!.kill).not.toHaveBeenCalled();
    children[0]!.exit();
    await supervisor.stop();
    expect(supervisor.status.message).toContain("partially changed");
    expect(spawn).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("refuses shutdown during active restore and cancels auto-restart even if it later succeeds", async () => {
    const restore = supervisor.applyOfflineRestore(
      "synthetic-plan",
      "synthetic-hash",
    );
    await vi.advanceTimersByTimeAsync(0);
    await expect(supervisor.stop()).rejects.toThrow("still be writing");
    expect(children[0]!.kill).not.toHaveBeenCalled();
    children[0]!.exit();
    await restore;
    expect(supervisor.status.state).toBe("stopped");
    expect(spawn).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("terminal shutdown freezes new lifecycle work even if the app stays open", async () => {
    const child = await ready();
    const shutdown = supervisor.shutdown();
    await expect(supervisor.start()).rejects.toThrow("shutdown has begun");
    await expect(
      supervisor.applyOfflineRestore("synthetic", "synthetic"),
    ).rejects.toThrow("shutdown has begun");
    child.exit();
    await shutdown;
    await expect(supervisor.start()).rejects.toThrow("shutdown has begun");
    await expect(
      supervisor.applyOfflineRestore("synthetic", "synthetic"),
    ).rejects.toThrow("shutdown has begun");
    await supervisor.shutdown();
    expect(spawn).toHaveBeenCalledTimes(2);
  });

  it("wall-clock changes cannot lengthen readiness observation", async () => {
    vi.mocked(supervisor.client.runtimeStatus).mockRejectedValue(
      new Error("offline"),
    );
    const starting = supervisor.start().catch((error: unknown) => error);
    children[0]!.exit();
    await vi.advanceTimersByTimeAsync(0);
    children[1]!.kill.mockImplementation(() => {
      children[1]!.exit(null, "SIGTERM");
      return true;
    });
    vi.setSystemTime(Date.now() - 86_400_000);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(await starting).toBeInstanceOf(Error);
    expect(supervisor.status.state).toBe("degraded");
    expect(supervisor.client.runDueBackupSchedules).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("restore creation failure is sanitized and never automatically restarts", async () => {
    const restore = supervisor
      .applyOfflineRestore("synthetic", "synthetic")
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(0);
    children[0]!.pid = undefined;
    children[0]!.emit("error", new Error("private command line"));
    expect(await restore).toBeInstanceOf(Error);
    expect(supervisor.status.message).not.toContain("private");
    await expect(supervisor.start()).rejects.toThrow("partially changed");
    await supervisor.shutdown();
    expect(children[0]!.kill).not.toHaveBeenCalled();
    expect(spawn).toHaveBeenCalledOnce();
  });

  it("publishes startup exclusivity before reentrant status listeners run", async () => {
    let nested: Promise<void> | undefined;
    supervisor.onStatus((status) => {
      if (status.message.includes("Preparing")) nested = supervisor.start();
    });
    const starting = supervisor.start();
    expect(nested).toBe(starting);
    expect(spawn).toHaveBeenCalledOnce();
    children[0]!.exit();
    await starting;
  });

  it("does not recreate a scheduler after a ready listener shuts down", async () => {
    const health = deferred<void>();
    vi.mocked(supervisor.client.runtimeStatus).mockReturnValue(health.promise);
    let stop: Promise<void> | undefined;
    supervisor.onStatus((status) => {
      if (status.state === "ready") stop = supervisor.stop();
    });
    const starting = supervisor.start();
    children[0]!.exit();
    await vi.advanceTimersByTimeAsync(0);
    children[1]!.kill.mockImplementation(() => {
      children[1]!.exit();
      return true;
    });
    health.resolve();
    await starting;
    await stop;
    expect(supervisor.status.state).toBe("stopped");
    expect(supervisor.client.runDueBackupSchedules).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("rechecks ownership after an applying-restore status listener requests shutdown", async () => {
    let stop: Promise<void> | undefined;
    supervisor.onStatus((status) => {
      if (status.message.includes("Applying verified"))
        stop = supervisor.stop();
    });
    await expect(
      supervisor.applyOfflineRestore("synthetic", "synthetic"),
    ).rejects.toThrow("cancelled before");
    await stop;
    expect(spawn).not.toHaveBeenCalled();
    expect(supervisor.status.state).toBe("stopped");
  });

  it("coalesces termination when shutdown overlaps migration timeout cleanup", async () => {
    const starting = supervisor.start();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(children[0]!.kill).toHaveBeenCalledOnce();
    const stop = supervisor.stop();
    expect(children[0]!.kill).toHaveBeenCalledOnce();
    children[0]!.exit(null, "SIGTERM");
    await Promise.all([starting, stop]);
    expect(children[0]!.kill).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });
});
