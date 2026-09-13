import { lstatSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, join, parse, resolve } from "node:path";

export const RESTORE_ADMISSION_MESSAGE =
  "Offline restore recovery is required or its safety status cannot be verified. Normal startup, new restores, and updates are blocked. Preserve the workspace, backups, staging files, restore-control folder, and original encryption key. Do not delete the restore guard or create a replacement key. The backend restore-status command can inspect admission without opening the database or loading a key. Authenticated restore-finalize requires the original key, a committed receipt, and matching restored files; an incomplete restore cannot be finalized this way. No automatic rollback is available.";

export class RestoreAdmissionError extends Error {
  constructor() {
    super(RESTORE_ADMISSION_MESSAGE);
    this.name = "RestoreAdmissionError";
  }
}

export const MISSING_MASTER_KEY_MESSAGE =
  "The original encryption key is missing from an existing workspace, or key-creation safety could not be verified. A replacement key will not be created. Preserve the database, workspace, restore-control history, backups, and any original master-key.bin copy. Recover the original protected key before reopening this workspace; a new key cannot decrypt existing data.";

export class MissingMasterKeyError extends Error {
  constructor() {
    super(MISSING_MASTER_KEY_MESSAGE);
    this.name = "MissingMasterKeyError";
  }
}

export interface RestoreAdmissionOptions {
  dataRoot: string;
  databaseUrl: string;
  projectRoot: string;
}

function missing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}

function equivalent(left: string, right: string): boolean {
  return process.platform === "win32"
    ? left.toLowerCase() === right.toLowerCase()
    : left === right;
}

// Read-only early admission, never a database probe or a recovery mutation.
// This is defense in depth: backend admission also owns an OS-backed lock.
function directoryIsSafe(path: string): boolean {
  if (process.platform === "win32" && path.startsWith("\\\\")) return false;
  let current = path;
  while (true) {
    try {
      const stats = lstatSync(current);
      if (!stats.isDirectory() || stats.isSymbolicLink()) return false;
      // Also refuse redirected ancestors (including Windows junctions).
      if (!equivalent(resolve(realpathSync.native(current)), current))
        return false;
    } catch (error) {
      if (!missing(error)) return false;
    }
    const parent = dirname(current);
    if (parent === current) return true;
    current = parent;
  }
}

function sqliteDatabasePath(
  options: RestoreAdmissionOptions,
): string | undefined {
  // Do not let a driver-qualified SQLite URL silently omit its database root.
  const sqlitePrefix = ["sqlite:///", "sqlite+pysqlite:///"].find((prefix) =>
    options.databaseUrl.startsWith(prefix),
  );
  const memoryOnly = ["sqlite://", "sqlite+pysqlite://"].includes(
    options.databaseUrl,
  );
  if (options.databaseUrl.startsWith("sqlite") && !sqlitePrefix && !memoryOnly)
    throw new RestoreAdmissionError();
  if (sqlitePrefix) {
    const databasePath = options.databaseUrl.slice(sqlitePrefix.length);
    if (databasePath !== ":memory:") {
      if (
        !databasePath ||
        databasePath.startsWith("file:") ||
        /[?#\0]/u.test(databasePath)
      )
        throw new RestoreAdmissionError();
      return isAbsolute(databasePath)
        ? resolve(databasePath)
        : resolve(options.projectRoot, databasePath);
    }
  }
  return undefined;
}

export function restoreAdmissionRoots(
  options: RestoreAdmissionOptions,
): string[] {
  const roots = [resolve(options.dataRoot)];
  const database = sqliteDatabasePath(options);
  if (database) roots.push(dirname(database));
  return roots.filter(
    (root, index) =>
      roots.findIndex((candidate) => equivalent(root, candidate)) === index,
  );
}

export function restoreAdmissionBlocked(
  options: RestoreAdmissionOptions,
): boolean {
  try {
    for (const root of restoreAdmissionRoots(options)) {
      if (root === parse(root).root || !directoryIsSafe(root)) return true;
      const control = join(root, "restore-control");
      if (!directoryIsSafe(control)) return true;
      try {
        // Existence alone blocks, including corrupt, empty, or non-file guards.
        lstatSync(join(control, "active.guard"));
        return true;
      } catch (error) {
        if (!missing(error)) return true;
      }
    }
    return false;
  } catch {
    return true;
  }
}

export function assertRestoreAdmission(options: RestoreAdmissionOptions): void {
  if (restoreAdmissionBlocked(options)) throw new RestoreAdmissionError();
}

export function assertMasterKeyCreationAdmission(
  options: RestoreAdmissionOptions,
): void {
  assertRestoreAdmission(options);
  try {
    const database = sqliteDatabasePath(options);
    const paths = [
      // Retain the desktop's original DB location even with an external override.
      join(resolve(options.dataRoot), "job-apply-pro.db"),
      ...(database ? [database] : []),
      ...restoreAdmissionRoots(options).map((root) =>
        join(root, "restore-control"),
      ),
    ];
    for (const path of paths) {
      try {
        // Any entry or inspection failure forbids replacement. No DB is opened.
        lstatSync(path);
        throw new MissingMasterKeyError();
      } catch (error) {
        if (!missing(error)) throw new MissingMasterKeyError();
      }
    }
  } catch {
    throw new MissingMasterKeyError();
  }
}
