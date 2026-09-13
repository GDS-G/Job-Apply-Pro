import electronUpdater from "electron-updater";
import { spawn, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UpdateManager } from "./update-manager.js";
import { BackendSupervisor } from "./backend-supervisor.js";

vi.mock("node:child_process", () => {
  const spawn = vi.fn();
  return { spawn, default: { spawn } };
});

vi.mock("electron-updater", async () => {
  const { EventEmitter } = await import("node:events");
  return {
    default: {
      autoUpdater: Object.assign(new EventEmitter(), {
        checkForUpdates: vi.fn(),
        downloadUpdate: vi.fn(),
        quitAndInstall: vi.fn(),
      }),
    },
  };
});
const { autoUpdater } = electronUpdater;
const downloaded = {
  version: "0.54.1-alpha.1",
  downloadedFile: "synthetic.exe",
  files: [],
  path: "synthetic.exe",
  sha512: "synthetic",
  releaseDate: "2026-09-12T00:00:00Z",
};

describe("update installation shutdown gate", () => {
  afterEach(() => {
    autoUpdater.removeAllListeners();
    vi.mocked(autoUpdater.quitAndInstall).mockReset();
    vi.mocked(spawn).mockReset();
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it("coalesces install and never launches the installer before shutdown proof", async () => {
    let finish!: () => void;
    const shutdown = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const updates = new UpdateManager(true, "0.54.0-alpha.1", shutdown);
    autoUpdater.emit("update-downloaded", downloaded);
    const install = updates.install();
    expect(updates.install()).toBe(install);
    expect(shutdown).toHaveBeenCalledOnce();
    expect(autoUpdater.quitAndInstall).not.toHaveBeenCalled();
    finish();
    await install;
    expect(autoUpdater.quitAndInstall).toHaveBeenCalledExactlyOnceWith(
      false,
      true,
    );
  });

  it("sanitizes shutdown failure and blocks installer launch", async () => {
    const updates = new UpdateManager(true, "0.54.0-alpha.1", async () => {
      throw new Error("private writer details");
    });
    autoUpdater.emit("update-downloaded", downloaded);
    await expect(updates.install()).rejects.toThrow("safe shutdown");
    expect(autoUpdater.quitAndInstall).not.toHaveBeenCalled();
    expect(updates.status.state).toBe("ERROR");
    expect(updates.status.message).not.toContain("private");
  });

  it("catches installer errors without promising an installation happened", async () => {
    vi.mocked(autoUpdater.quitAndInstall).mockImplementation(() => {
      throw new Error("private installer path");
    });
    const updates = new UpdateManager(
      true,
      "0.54.0-alpha.1",
      async () => undefined,
    );
    autoUpdater.emit("update-downloaded", downloaded);
    await expect(updates.install()).rejects.toThrow("installation was blocked");
    expect(updates.status.state).toBe("ERROR");
    expect(updates.status.message).not.toContain("private");
  });

  it("does not shut down for disabled or not-downloaded updates", async () => {
    const shutdown = vi.fn(async () => undefined);
    await new UpdateManager(false, "0.54.0-alpha.1", shutdown).install();
    await new UpdateManager(true, "0.54.0-alpha.1", shutdown).install();
    expect(shutdown).not.toHaveBeenCalled();
    expect(autoUpdater.quitAndInstall).not.toHaveBeenCalled();
  });

  it.each(["nonzero", "timeout then late exit"])(
    "blocks automatic updater relaunch after restore %s, while allowing deliberate quit",
    async (outcome) => {
      vi.useFakeTimers();
      const writer = Object.assign(new EventEmitter(), {
        pid: 4111,
        kill: vi.fn(() => true),
      });
      vi.mocked(spawn).mockReturnValue(writer as unknown as ChildProcess);
      const supervisor = new BackendSupervisor({
        projectRoot: "C:/synthetic/project",
        dataRoot: "C:/synthetic/data",
        baseUrl: "http://127.0.0.1:8765/api/v1",
        apiToken: "synthetic-token",
        masterKey: "synthetic-key",
        databaseUrl: "sqlite:///synthetic.db",
        backendExecutable: "C:/synthetic/backend.exe",
      });
      const restore = supervisor
        .applyOfflineRestore("synthetic-plan", "synthetic-hash")
        .catch((error: unknown) => error);
      await vi.advanceTimersByTimeAsync(0);
      if (outcome === "nonzero") writer.emit("exit", 1, null);
      else await vi.advanceTimersByTimeAsync(120_000);
      expect(await restore).toBeInstanceOf(Error);
      if (outcome !== "nonzero") writer.emit("exit", 0, null);
      const updates = new UpdateManager(true, "0.54.0-alpha.1", () =>
        supervisor.prepareUpdate(),
      );
      autoUpdater.emit("update-downloaded", downloaded);
      await expect(updates.install()).rejects.toThrow("safe shutdown");
      expect(autoUpdater.quitAndInstall).not.toHaveBeenCalled();
      expect(supervisor.status.message).toContain("partially changed");
      expect(writer.kill).not.toHaveBeenCalled();
      await supervisor.shutdown();
      expect(supervisor.status.state).toBe("degraded");
      expect(spawn).toHaveBeenCalledOnce();
      expect(vi.getTimerCount()).toBe(0);
    },
  );
});
