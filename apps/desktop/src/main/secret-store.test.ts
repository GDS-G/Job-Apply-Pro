import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { mkdir, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { safeStorage } from "electron";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadOrCreateMasterKey } from "./secret-store.js";

vi.mock("electron", () => ({
  safeStorage: {
    isEncryptionAvailable: vi.fn(() => true),
    encryptString: vi.fn((value: string) => Buffer.from(value)),
    decryptString: vi.fn((value: Buffer) => value.toString()),
  },
}));
vi.mock("node:fs/promises", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs/promises")>();
  const exports = {
    ...actual,
    readFile: vi.fn(actual.readFile),
    mkdir: vi.fn(actual.mkdir),
  };
  return { ...exports, default: exports };
});

describe("master key restore admission", () => {
  let root: string;
  let keyPath: string;
  beforeEach(() => {
    vi.clearAllMocks();
    root = realpathSync.native(
      mkdtempSync(join(tmpdir(), "jap-key-admission-")),
    );
    keyPath = join(root, "secrets", "master-key.bin");
  });
  afterEach(() => {
    rmSync(root, { recursive: true, force: true });
  });
  const options = () => ({
    dataRoot: root,
    databaseUrl: `sqlite:///${join(root, "candidate.db")}`,
    projectRoot: root,
  });
  const guard = () => {
    mkdirSync(join(root, "restore-control"), { recursive: true });
    writeFileSync(join(root, "restore-control", "active.guard"), "uncertain");
  };

  it("creates a protected key normally when admission is clear", async () => {
    const key = await loadOrCreateMasterKey(keyPath, options());
    expect(Buffer.from(key, "base64")).toHaveLength(32);
    expect(safeStorage.encryptString).toHaveBeenCalledOnce();
    expect(readFileSync(keyPath).toString()).toBe(key);
  });

  it("loads an existing key without regenerating it", async () => {
    mkdirSync(join(root, "secrets"));
    writeFileSync(keyPath, "synthetic protected key");
    expect(await loadOrCreateMasterKey(keyPath, options())).toBe(
      "synthetic protected key",
    );
    expect(safeStorage.encryptString).not.toHaveBeenCalled();
  });

  it.each(["configured", "overridden", "desktop-default"])(
    "refuses a replacement key for an existing exact database path (%s)",
    async (location) => {
      const admission = options();
      let database = join(root, "candidate.db");
      if (location === "overridden") {
        const otherRoot = join(root, "alternate");
        mkdirSync(otherRoot);
        database = join(otherRoot, "external.db");
        admission.databaseUrl = `sqlite+pysqlite:///${database}`;
      } else if (location === "desktop-default") {
        database = join(root, "job-apply-pro.db");
        admission.databaseUrl = "sqlite:///:memory:";
      }
      writeFileSync(database, "synthetic existing database");
      await expect(loadOrCreateMasterKey(keyPath, admission)).rejects.toThrow(
        "A replacement key will not be created",
      );
      expect(existsSync(keyPath)).toBe(false);
      expect(safeStorage.encryptString).not.toHaveBeenCalled();
      expect(readFileSync(database, "utf8")).toBe(
        "synthetic existing database",
      );
    },
  );

  it.each(["workspace", "derived"])(
    "refuses a missing key with inactive restore-control history (%s root)",
    async (location) => {
      const alternate = join(root, "alternate");
      mkdirSync(alternate);
      const admission = {
        ...options(),
        databaseUrl: `sqlite:///${join(alternate, "external.db")}`,
      };
      const history = join(
        location === "workspace" ? root : alternate,
        "restore-control",
      );
      mkdirSync(history);
      writeFileSync(join(history, "admission.lock"), "synthetic history");
      await expect(loadOrCreateMasterKey(keyPath, admission)).rejects.toThrow(
        "original protected key",
      );
      expect(existsSync(keyPath)).toBe(false);
      expect(safeStorage.encryptString).not.toHaveBeenCalled();
      expect(existsSync(join(history, "active.guard"))).toBe(false);
    },
  );

  it("loads an existing key normally with inactive restore history", async () => {
    mkdirSync(join(root, "secrets"));
    mkdirSync(join(root, "restore-control"));
    writeFileSync(keyPath, "original protected key");
    writeFileSync(join(root, "candidate.db"), "synthetic existing database");
    expect(await loadOrCreateMasterKey(keyPath, options())).toBe(
      "original protected key",
    );
    expect(safeStorage.encryptString).not.toHaveBeenCalled();
  });

  it("rechecks creation admission after awaiting the secrets directory", async () => {
    vi.mocked(mkdir).mockImplementationOnce(async () => {
      mkdirSync(join(root, "secrets"));
      mkdirSync(join(root, "restore-control"));
      return undefined;
    });
    await expect(loadOrCreateMasterKey(keyPath, options())).rejects.toThrow(
      "A replacement key will not be created",
    );
    expect(existsSync(keyPath)).toBe(false);
  });

  it.each([false, true])(
    "blocks before reading or creating any key when a guard exists (existing=%s)",
    async (existing) => {
      if (existing) {
        mkdirSync(join(root, "secrets"));
        writeFileSync(keyPath, "original protected key");
      }
      guard();
      await expect(loadOrCreateMasterKey(keyPath, options())).rejects.toThrow(
        "original encryption key",
      );
      expect(readFile).not.toHaveBeenCalled();
      expect(safeStorage.encryptString).not.toHaveBeenCalled();
      expect(safeStorage.decryptString).not.toHaveBeenCalled();
    },
  );

  it("rechecks admission if a guard appears while reading a missing key", async () => {
    vi.mocked(readFile).mockImplementationOnce(async () => {
      guard();
      throw Object.assign(new Error("synthetic missing key"), {
        code: "ENOENT",
      });
    });
    await expect(loadOrCreateMasterKey(keyPath, options())).rejects.toThrow(
      "replacement key",
    );
    expect(safeStorage.encryptString).not.toHaveBeenCalled();
  });
});
