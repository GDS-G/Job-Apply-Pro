import { EventEmitter } from "node:events";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough } from "node:stream";

import { dialog, safeStorage } from "electron";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MissingMasterKeyError } from "./restore-admission.js";
import {
  InstalledRecoveryError,
  runInstalledRestoreRecovery,
} from "./restore-recovery-controller.js";

interface ChildResult {
  stdout?: string | Buffer;
  stderr?: string | Buffer;
  code?: number;
  signal?: NodeJS.Signals | null;
  error?: Error;
  effect?: () => void;
  hung?: boolean;
  killError?: Error;
}

const mocks = vi.hoisted(() => ({
  spawn: vi.fn(),
  results: [] as ChildResult[],
  showMessageBox: vi.fn(),
  encryptString: vi.fn(),
  decryptString: vi.fn(),
  children: [] as { kill: ReturnType<typeof vi.fn> }[],
}));

vi.mock("node:child_process", () => ({
  spawn: mocks.spawn,
  default: { spawn: mocks.spawn },
}));
vi.mock("electron", () => ({
  dialog: { showMessageBox: mocks.showMessageBox },
  safeStorage: {
    isEncryptionAvailable: vi.fn(() => true),
    encryptString: mocks.encryptString,
    decryptString: mocks.decryptString,
  },
}));

const OPERATION_ID = "76543210-4321-4321-8321-210987654321";
const FINGERPRINT = "a".repeat(64);
const MASTER_KEY = Buffer.alloc(32, 7).toString("base64");
const WRONG_KEY = Buffer.alloc(32, 9).toString("base64");

function inspection(
  state: "INTERRUPTED" | "ROLLING_BACK" | "APPLIED" | "ROLLED_BACK",
): string {
  const rollback = state === "INTERRUPTED" || state === "ROLLING_BACK";
  return JSON.stringify({
    operation_id: OPERATION_ID,
    version: 2,
    state,
    rollback_supported: rollback,
    review_fingerprint: rollback ? FINGERPRINT : null,
  });
}

describe("installed restore recovery controller", () => {
  let root: string;
  let resourcesPath: string;
  let keyPath: string;
  let guardPath: string;

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.results.length = 0;
    mocks.children.length = 0;
    root = realpathSync.native(
      mkdtempSync(join(tmpdir(), "jap-installed-recovery-")),
    );
    resourcesPath = join(root, "installed-resources");
    keyPath = join(root, "secrets", "master-key.bin");
    guardPath = join(root, "restore-control", "active.guard");
    mkdirSync(join(root, "secrets"), { recursive: true });
    mkdirSync(join(root, "restore-control"), { recursive: true });
    writeFileSync(keyPath, "synthetic protected key");
    writeFileSync(guardPath, OPERATION_ID);
    mocks.decryptString.mockReturnValue(MASTER_KEY);
    mocks.spawn.mockImplementation(() => {
      const result = mocks.results.shift();
      if (!result) throw new Error("Missing synthetic child result");
      const child = new EventEmitter() as EventEmitter & {
        stdout: PassThrough;
        stderr: PassThrough;
        kill: ReturnType<typeof vi.fn>;
      };
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child.kill = vi.fn(() => {
        if (result.killError) throw result.killError;
        return true;
      });
      mocks.children.push(child);
      queueMicrotask(() => {
        if (result.hung) return;
        if (result.error) {
          child.emit("error", result.error);
          return;
        }
        result.effect?.();
        child.stdout.end(result.stdout ?? "");
        child.stderr.end(result.stderr ?? "");
        child.emit("close", result.code ?? 0, result.signal ?? null);
      });
      return child;
    });
    mocks.showMessageBox.mockResolvedValue({
      response: 0,
      checkboxChecked: false,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    rmSync(root, { recursive: true, force: true });
    vi.unstubAllEnvs();
  });

  const options = () => ({
    dataRoot: root,
    databaseUrl: `sqlite:///${join(root, "job-apply-pro.db").replaceAll("\\", "/")}`,
    projectRoot: resourcesPath,
    resourcesPath,
    masterKeyPath: keyPath,
  });

  it("uses the protected key and forwards only the authenticated exact rollback review", async () => {
    vi.stubEnv("JAP_MASTER_KEY", "untrusted-parent-override");
    mocks.decryptString.mockImplementation((value: Buffer) => {
      expect(value.toString()).toBe("synthetic protected key");
      return MASTER_KEY;
    });
    mocks.results.push(
      { stdout: inspection("INTERRUPTED") },
      { stdout: "", effect: () => rmSync(guardPath) },
      { stdout: inspection("ROLLED_BACK") },
    );
    mocks.showMessageBox
      .mockResolvedValueOnce({ response: 1, checkboxChecked: false })
      .mockResolvedValueOnce({ response: 0, checkboxChecked: false });

    await expect(runInstalledRestoreRecovery(options())).resolves.toBe(
      "rolled-back",
    );

    expect(safeStorage.decryptString).toHaveBeenCalledOnce();
    expect(safeStorage.encryptString).not.toHaveBeenCalled();
    expect(process.env.JAP_MASTER_KEY).toBe("untrusted-parent-override");
    expect(mocks.spawn).toHaveBeenCalledTimes(3);
    const executable = join(
      resourcesPath,
      "backend",
      "job-apply-pro-backend.exe",
    );
    expect(mocks.spawn.mock.calls.map((call) => call[0])).toEqual([
      executable,
      executable,
      executable,
    ]);
    expect(mocks.spawn.mock.calls.map((call) => call[1])).toEqual([
      ["restore-inspect", "--operation-id", OPERATION_ID],
      [
        "restore-rollback",
        "--operation-id",
        OPERATION_ID,
        "--fingerprint",
        FINGERPRINT,
      ],
      ["restore-inspect", "--operation-id", OPERATION_ID],
    ]);
    for (const call of mocks.spawn.mock.calls) {
      expect(call[2]).toMatchObject({
        cwd: resourcesPath,
        windowsHide: true,
        shell: false,
        detached: false,
        stdio: ["ignore", "pipe", "pipe"],
      });
      expect(call[2].env.JAP_MASTER_KEY).toBe(MASTER_KEY);
      expect(call[2].env.JAP_API_TOKEN).toBeUndefined();
      expect(call[2].env.PYTHONPATH).toBeUndefined();
    }
    expect(mocks.showMessageBox.mock.calls[0]![0]).toMatchObject({
      defaultId: 0,
      cancelId: 0,
      buttons: ["Keep workspace blocked", "Roll back exact restore"],
    });
  });

  it("keeps cancel as the default and performs no rollback mutation", async () => {
    mocks.results.push({ stdout: inspection("INTERRUPTED") });

    await expect(runInstalledRestoreRecovery(options())).resolves.toBe(
      "cancelled",
    );

    expect(mocks.spawn).toHaveBeenCalledOnce();
    expect(mocks.spawn.mock.calls[0]![1][0]).toBe("restore-inspect");
    expect(readFileSync(guardPath, "ascii")).toBe(OPERATION_ID);
    expect(readFileSync(keyPath, "utf8")).toBe("synthetic protected key");
    expect(safeStorage.encryptString).not.toHaveBeenCalled();
  });

  it.each(["APPLIED", "ROLLED_BACK"] as const)(
    "offers exact finalization for an authenticated terminal %s receipt",
    async (terminalState) => {
      mocks.results.push(
        { stdout: inspection(terminalState) },
        { stdout: "", effect: () => rmSync(guardPath) },
        { stdout: inspection(terminalState) },
      );
      mocks.showMessageBox
        .mockResolvedValueOnce({ response: 1, checkboxChecked: false })
        .mockResolvedValueOnce({ response: 0, checkboxChecked: false });

      await expect(runInstalledRestoreRecovery(options())).resolves.toBe(
        "finalized",
      );

      expect(mocks.spawn.mock.calls.map((call) => call[1])).toEqual([
        ["restore-inspect", "--operation-id", OPERATION_ID],
        ["restore-finalize", "--operation-id", OPERATION_ID],
        ["restore-inspect", "--operation-id", OPERATION_ID],
      ]);
      expect(mocks.showMessageBox.mock.calls[0]![0]).toMatchObject({
        defaultId: 0,
        cancelId: 0,
        buttons: ["Keep workspace blocked", "Finalize exact restore state"],
      });
      expect(mocks.showMessageBox.mock.calls[0]![0].detail).toContain(
        `terminal ${terminalState} receipt`,
      );
      expect(() => readFileSync(guardPath)).toThrow();
      expect(safeStorage.encryptString).not.toHaveBeenCalled();
    },
  );

  it("keeps an authenticated terminal receipt blocked when finalization is cancelled", async () => {
    mocks.results.push({ stdout: inspection("APPLIED") });

    await expect(runInstalledRestoreRecovery(options())).resolves.toBe(
      "cancelled",
    );

    expect(mocks.spawn).toHaveBeenCalledOnce();
    expect(mocks.spawn.mock.calls[0]![1][0]).toBe("restore-inspect");
    expect(readFileSync(guardPath, "ascii")).toBe(OPERATION_ID);
    expect(mocks.showMessageBox.mock.calls[0]![0]).toMatchObject({
      defaultId: 0,
      cancelId: 0,
    });
  });

  it.each([
    ["rollback", "INTERRUPTED", "restore-rollback"],
    ["finalization", "APPLIED", "restore-finalize"],
  ] as const)(
    "rejects unexpected stdout from the %s mutation command",
    async (_label, initialState, command) => {
      mocks.results.push(
        { stdout: inspection(initialState) },
        { stdout: "unexpected mutation output" },
      );
      mocks.showMessageBox.mockResolvedValueOnce({
        response: 1,
        checkboxChecked: false,
      });

      await expect(
        runInstalledRestoreRecovery(options()),
      ).rejects.toBeInstanceOf(InstalledRecoveryError);

      expect(mocks.spawn).toHaveBeenCalledTimes(2);
      expect(mocks.spawn.mock.calls[1]![1][0]).toBe(command);
      expect(mocks.showMessageBox).toHaveBeenCalledOnce();
      expect(readFileSync(guardPath, "ascii")).toBe(OPERATION_ID);
    },
  );

  it("rejects a post-finalization inspection whose authenticated terminal state changed", async () => {
    mocks.results.push(
      { stdout: inspection("APPLIED") },
      { stdout: "", effect: () => rmSync(guardPath) },
      { stdout: inspection("ROLLED_BACK") },
    );
    mocks.showMessageBox.mockResolvedValueOnce({
      response: 1,
      checkboxChecked: false,
    });

    await expect(runInstalledRestoreRecovery(options())).rejects.toBeInstanceOf(
      InstalledRecoveryError,
    );

    expect(mocks.spawn).toHaveBeenCalledTimes(3);
    expect(mocks.showMessageBox).toHaveBeenCalledOnce();
  });

  it("rejects terminal reinspection when the recovery guard was not cleared", async () => {
    mocks.results.push(
      { stdout: inspection("APPLIED") },
      { stdout: "" },
      { stdout: inspection("APPLIED") },
    );
    mocks.showMessageBox.mockResolvedValueOnce({
      response: 1,
      checkboxChecked: false,
    });

    await expect(runInstalledRestoreRecovery(options())).rejects.toBeInstanceOf(
      InstalledRecoveryError,
    );

    expect(mocks.spawn).toHaveBeenCalledTimes(3);
    expect(readFileSync(guardPath, "ascii")).toBe(OPERATION_ID);
    expect(mocks.showMessageBox).toHaveBeenCalledOnce();
  });

  it("rejects legacy recovery evidence without offering a native mutation", async () => {
    mocks.results.push({
      stdout: JSON.stringify({
        operation_id: OPERATION_ID,
        version: 1,
        state: "RECOVERY_REQUIRED",
        rollback_supported: false,
        review_fingerprint: null,
      }),
    });

    await expect(runInstalledRestoreRecovery(options())).rejects.toBeInstanceOf(
      InstalledRecoveryError,
    );

    expect(mocks.spawn).toHaveBeenCalledOnce();
    expect(dialog.showMessageBox).not.toHaveBeenCalled();
    expect(readFileSync(guardPath, "ascii")).toBe(OPERATION_ID);
  });

  it.each([undefined, new Error("synthetic kill refusal")])(
    "fails a hung child at the exact command timeout even if kill throws",
    async (killError) => {
      const observedDelays: number[] = [];
      const realSetTimeout = globalThis.setTimeout;
      const timeout = vi.spyOn(globalThis, "setTimeout").mockImplementation(((
        handler: TimerHandler,
        delay?: number,
      ) => {
        observedDelays.push(delay ?? 0);
        const handle = realSetTimeout(() => undefined, 600_000);
        queueMicrotask(() => {
          if (typeof handler === "function") handler();
        });
        return handle;
      }) as unknown as typeof setTimeout);
      mocks.results.push({
        hung: true,
        ...(killError ? { killError } : {}),
      });

      try {
        await expect(
          runInstalledRestoreRecovery(options()),
        ).rejects.toBeInstanceOf(InstalledRecoveryError);
      } finally {
        timeout.mockRestore();
      }

      expect(observedDelays).toEqual([60_000]);
      expect(mocks.children).toHaveLength(1);
      expect(mocks.children[0]!.kill).toHaveBeenCalledOnce();
      expect(dialog.showMessageBox).not.toHaveBeenCalled();
      expect(readFileSync(guardPath, "ascii")).toBe(OPERATION_ID);
    },
  );

  it("does not create a replacement when the protected key is missing", async () => {
    rmSync(keyPath);

    await expect(runInstalledRestoreRecovery(options())).rejects.toBeInstanceOf(
      MissingMasterKeyError,
    );

    expect(safeStorage.decryptString).not.toHaveBeenCalled();
    expect(safeStorage.encryptString).not.toHaveBeenCalled();
    expect(mocks.spawn).not.toHaveBeenCalled();
    expect(readFileSync(guardPath, "ascii")).toBe(OPERATION_ID);
  });

  it("does not create a replacement when OS protection cannot decrypt the existing key", async () => {
    mocks.decryptString.mockImplementation(() => {
      throw new Error("synthetic wrong OS protection context");
    });

    await expect(runInstalledRestoreRecovery(options())).rejects.toBeInstanceOf(
      MissingMasterKeyError,
    );

    expect(safeStorage.encryptString).not.toHaveBeenCalled();
    expect(mocks.spawn).not.toHaveBeenCalled();
    expect(readFileSync(keyPath, "utf8")).toBe("synthetic protected key");
    expect(readFileSync(guardPath, "ascii")).toBe(OPERATION_ID);
  });

  it("does not create a replacement when an existing protected key cannot authenticate recovery", async () => {
    mocks.decryptString.mockReturnValue(WRONG_KEY);
    mocks.results.push({
      code: 3,
      stderr: "Offline restore admission failed.",
    });

    await expect(runInstalledRestoreRecovery(options())).rejects.toBeInstanceOf(
      InstalledRecoveryError,
    );

    expect(safeStorage.encryptString).not.toHaveBeenCalled();
    expect(mocks.spawn).toHaveBeenCalledOnce();
    expect(mocks.spawn.mock.calls[0]![2].env.JAP_MASTER_KEY).toBe(WRONG_KEY);
    expect(readFileSync(keyPath, "utf8")).toBe("synthetic protected key");
    expect(readFileSync(guardPath, "ascii")).toBe(OPERATION_ID);
  });

  it.each([
    ["malformed JSON", { stdout: "not-json" }],
    ["oversized output", { stdout: "x".repeat(32 * 1024 + 1) }],
    ["nonzero exit", { stdout: inspection("INTERRUPTED"), code: 3 }],
    [
      "unexpected stderr",
      { stdout: inspection("INTERRUPTED"), stderr: "private path" },
    ],
  ] satisfies [string, ChildResult][])(
    "fails closed on %s without presenting a mutation action",
    async (_label, result) => {
      mocks.results.push(result);

      await expect(
        runInstalledRestoreRecovery(options()),
      ).rejects.toBeInstanceOf(InstalledRecoveryError);

      expect(mocks.spawn).toHaveBeenCalledOnce();
      expect(dialog.showMessageBox).not.toHaveBeenCalled();
      expect(readFileSync(guardPath, "ascii")).toBe(OPERATION_ID);
      expect(safeStorage.encryptString).not.toHaveBeenCalled();
    },
  );

  it("rejects an inspection that changes the guarded operation or adds fields", async () => {
    mocks.results.push({
      stdout: JSON.stringify({
        ...JSON.parse(inspection("INTERRUPTED")),
        operation_id: "12345678-1234-4234-8234-123456789abc",
        extra: "not accepted",
      }),
    });

    await expect(runInstalledRestoreRecovery(options())).rejects.toBeInstanceOf(
      InstalledRecoveryError,
    );

    expect(dialog.showMessageBox).not.toHaveBeenCalled();
    expect(mocks.spawn).toHaveBeenCalledOnce();
  });
});
