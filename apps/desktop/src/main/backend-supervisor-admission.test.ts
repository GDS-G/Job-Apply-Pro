import { spawn, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BackendClient } from "./backend-client.js";
import { BackendSupervisor } from "./backend-supervisor.js";

vi.mock("node:child_process", () => {
  const spawn = vi.fn();
  return { spawn, default: { spawn } };
});

class FakeChild extends EventEmitter {
  pid = 4200;
  kill = vi.fn((_signal?: NodeJS.Signals) => {
    this.exit();
    return true;
  });
  exit(): void {
    this.emit("exit", 0, null);
  }
}

describe("desktop durable restore lifecycle gate", () => {
  let root: string;
  let supervisor: BackendSupervisor;
  let children: FakeChild[];
  beforeEach(() => {
    vi.useFakeTimers();
    root = mkdtempSync(join(tmpdir(), "jap-supervisor-admission-"));
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
    supervisor = new BackendSupervisor({
      projectRoot: root,
      dataRoot: root,
      baseUrl: "http://127.0.0.1:8765/api/v1",
      apiToken: "synthetic-token",
      masterKey: "synthetic-key",
      databaseUrl: `sqlite:///${join(root, "candidate.db")}`,
      backendExecutable: join(root, "synthetic-backend.exe"),
    });
  });
  afterEach(async () => {
    for (const child of children) child.exit();
    await supervisor.shutdown();
    vi.clearAllTimers();
    vi.restoreAllMocks();
    vi.mocked(spawn).mockReset();
    vi.useRealTimers();
    rmSync(root, { recursive: true, force: true });
  });
  const guard = () => {
    mkdirSync(join(root, "restore-control"), { recursive: true });
    writeFileSync(join(root, "restore-control", "active.guard"), "uncertain");
  };
  const ready = async () => {
    const startup = supervisor.start();
    children[0]!.exit();
    await startup;
  };

  it("blocks startup, new restore, and update while allowing deliberate quit", async () => {
    guard();
    await expect(supervisor.start()).rejects.toThrow("recovery is required");
    await expect(
      supervisor.applyOfflineRestore("synthetic", "synthetic"),
    ).rejects.toThrow("recovery is required");
    await expect(supervisor.prepareUpdate()).rejects.toThrow(
      "recovery is required",
    );
    await expect(supervisor.shutdown()).resolves.toBeUndefined();
    expect(spawn).not.toHaveBeenCalled();
  });

  it("passes the canonical desktop workspace root to backend admission", async () => {
    await ready();
    for (const call of vi.mocked(spawn).mock.calls)
      expect(call[2]?.env?.JAP_WORKSPACE_ROOT).toBe(root);
  });

  it("rechecks the guard after migration exit before launching the server", async () => {
    const startup = supervisor.start();
    guard();
    children[0]!.exit();
    await expect(startup).rejects.toThrow("recovery is required");
    expect(spawn).toHaveBeenCalledOnce();
    expect(supervisor.status.state).toBe("degraded");
  });

  it("does not interpret writer exit zero as permission to ignore a durable guard", async () => {
    const restore = supervisor.applyOfflineRestore("synthetic", "synthetic");
    await vi.advanceTimersByTimeAsync(0);
    guard();
    children[0]!.exit();
    await expect(restore).rejects.toThrow("recovery is required");
    expect(spawn).toHaveBeenCalledOnce();
    expect(supervisor.status.state).toBe("degraded");
    await expect(supervisor.start()).rejects.toThrow("recovery is required");
    expect(children[0]!.kill).not.toHaveBeenCalled();
  });

  it("rechecks update admission after shutdown proof", async () => {
    await ready();
    children[1]!.kill.mockImplementation(() => {
      guard();
      children[1]!.exit();
      return true;
    });
    await expect(supervisor.prepareUpdate()).rejects.toThrow(
      "recovery is required",
    );
    expect(children[1]!.kill).toHaveBeenCalledOnce();
    expect(spawn).toHaveBeenCalledTimes(2);
  });

  it("does not recursively publish the same admission failure to a reentrant listener", async () => {
    guard();
    const nested: Promise<void>[] = [];
    supervisor.onStatus((status) => {
      if (status.state === "degraded")
        nested.push(supervisor.start().catch(() => undefined));
    });
    await expect(supervisor.start()).rejects.toThrow("recovery is required");
    await Promise.all(nested);
    expect(nested).toHaveLength(1);
    expect(spawn).not.toHaveBeenCalled();
  });
});
