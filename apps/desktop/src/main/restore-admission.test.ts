import * as fs from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  assertRestoreAdmission,
  RESTORE_ADMISSION_MESSAGE,
  restoreAdmissionBlocked,
  restoreAdmissionRoots,
} from "./restore-admission.js";

vi.mock("node:fs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs")>();
  const exports = { ...actual, lstatSync: vi.fn(actual.lstatSync) };
  return { ...exports, default: exports };
});

describe("DB-free durable restore admission", () => {
  let workspace: string;
  let options: { dataRoot: string; databaseUrl: string; projectRoot: string };
  beforeEach(() => {
    workspace = fs.mkdtempSync(join(tmpdir(), "jap-restore-admission-"));
    options = {
      dataRoot: join(workspace, "data"),
      databaseUrl: `sqlite:///${join(workspace, "data", "candidate.db")}`,
      projectRoot: workspace,
    };
  });
  afterEach(() => {
    vi.mocked(fs.lstatSync).mockReset();
    fs.rmSync(workspace, { recursive: true, force: true });
  });

  function control(root = options.dataRoot): string {
    const path = join(root, "restore-control");
    fs.mkdirSync(path, { recursive: true });
    return path;
  }

  it("accepts an absent workspace without creating directories or DB", () => {
    expect(restoreAdmissionBlocked(options)).toBe(false);
    expect(fs.readdirSync(workspace)).toEqual([]);
  });

  it.each(["", "corrupt operation id", "f8119345-5d90-4264-bcac-abd94d64a8e2"])(
    "blocks guard existence without interpreting its contents (%s)",
    (contents) => {
      const guard = join(control(), "active.guard");
      fs.writeFileSync(guard, contents);
      expect(restoreAdmissionBlocked(options)).toBe(true);
      expect(() => assertRestoreAdmission(options)).toThrow(
        RESTORE_ADMISSION_MESSAGE,
      );
      expect(fs.readFileSync(guard, "utf8")).toBe(contents);
      expect(fs.existsSync(join(options.dataRoot, "candidate.db"))).toBe(false);
    },
  );

  it("blocks non-file guards and non-directory control paths", () => {
    fs.mkdirSync(join(control(), "active.guard"));
    expect(restoreAdmissionBlocked(options)).toBe(true);
    const otherRoot = join(workspace, "other");
    fs.mkdirSync(otherRoot);
    fs.writeFileSync(join(otherRoot, "restore-control"), "not a directory");
    expect(restoreAdmissionBlocked({ ...options, dataRoot: otherRoot })).toBe(
      true,
    );
  });

  it("checks both the explicit workspace and an overridden SQLite parent", () => {
    const alternate = join(workspace, "alternate");
    const override = {
      ...options,
      databaseUrl: `sqlite:///${join(alternate, "candidate.db")}`,
    };
    expect(restoreAdmissionRoots(override)).toEqual([
      options.dataRoot,
      alternate,
    ]);
    fs.writeFileSync(join(control(), "active.guard"), "original guard");
    expect(restoreAdmissionBlocked(override)).toBe(true);
    const alternateOptions = { ...override, dataRoot: join(workspace, "new") };
    expect(restoreAdmissionBlocked(alternateOptions)).toBe(false);
    fs.writeFileSync(join(control(alternate), "active.guard"), "db guard");
    expect(restoreAdmissionBlocked(alternateOptions)).toBe(true);
  });

  it("resolves relative database paths using the child working directory", () => {
    expect(
      restoreAdmissionRoots({ ...options, databaseUrl: "sqlite:///db/app.db" }),
    ).toEqual([options.dataRoot, join(workspace, "db")]);
    expect(
      restoreAdmissionRoots({ ...options, databaseUrl: "sqlite:///:memory:" }),
    ).toEqual([options.dataRoot]);
  });

  it("derives the same guarded root for the supported pysqlite driver URL", () => {
    const alternate = join(workspace, "alternate");
    const driverOptions = {
      ...options,
      databaseUrl: `sqlite+pysqlite:///${join(alternate, "candidate.db")}`,
    };
    expect(restoreAdmissionRoots(driverOptions)).toEqual([
      options.dataRoot,
      alternate,
    ]);
    fs.writeFileSync(join(control(alternate), "active.guard"), "db guard");
    expect(restoreAdmissionBlocked(driverOptions)).toBe(true);
  });

  it.each(["sqlite://", "sqlite+pysqlite://", "sqlite+pysqlite:///:memory:"])(
    "permits genuine memory-only SQLite URLs while retaining the workspace gate (%s)",
    (databaseUrl) => {
      expect(restoreAdmissionRoots({ ...options, databaseUrl })).toEqual([
        options.dataRoot,
      ]);
      expect(restoreAdmissionBlocked({ ...options, databaseUrl })).toBe(false);
      fs.writeFileSync(join(control(), "active.guard"), "workspace guard");
      expect(restoreAdmissionBlocked({ ...options, databaseUrl })).toBe(true);
    },
  );

  it.each([
    "sqlite:///",
    "sqlite+pysqlite://candidate.db",
    "sqlite+unsupported:///candidate.db",
    "sqlite:///file:relative.db",
    "sqlite+pysqlite:///file:relative.db",
    "sqlite:///candidate.db?mode=ro",
    "sqlite:///bad\0name",
  ])("fails closed on an ambiguous database path (%s)", (databaseUrl) => {
    expect(restoreAdmissionBlocked({ ...options, databaseUrl })).toBe(true);
  });

  it("fails closed on filesystem permission and unexpected stat errors", () => {
    vi.mocked(fs.lstatSync).mockImplementation(() => {
      throw Object.assign(new Error("private path"), { code: "EACCES" });
    });
    expect(restoreAdmissionBlocked(options)).toBe(true);
    expect(() => assertRestoreAdmission(options)).toThrow(
      RESTORE_ADMISSION_MESSAGE,
    );
    expect(RESTORE_ADMISSION_MESSAGE).not.toContain(workspace);
  });

  it("rejects symlink or junction control paths and redirected ancestors", () => {
    const real = join(workspace, "real");
    fs.mkdirSync(real);
    fs.mkdirSync(options.dataRoot);
    fs.symlinkSync(real, join(options.dataRoot, "restore-control"), "junction");
    expect(restoreAdmissionBlocked(options)).toBe(true);
    const alias = join(workspace, "alias");
    fs.symlinkSync(real, alias, "junction");
    expect(
      restoreAdmissionBlocked({
        ...options,
        dataRoot: join(alias, "nested"),
        databaseUrl: "sqlite:///:memory:",
      }),
    ).toBe(true);
  });

  it("rejects non-directory workspace ancestors without opening files", () => {
    fs.writeFileSync(options.dataRoot, "not a folder");
    expect(restoreAdmissionBlocked(options)).toBe(true);
    expect(dirname(resolve(options.dataRoot))).toBe(workspace);
  });
});
