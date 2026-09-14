import { createHash, randomBytes } from "node:crypto";
import { createReadStream } from "node:fs";
import {
  cp,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
  sep,
} from "node:path";
import { createServer } from "node:net";

import { dialog, safeStorage } from "electron";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BackendSupervisor } from "./backend-supervisor.js";
import { runInstalledRestoreRecovery } from "./restore-recovery-controller.js";

const electron = vi.hoisted(() => ({
  showMessageBox: vi.fn(),
  isEncryptionAvailable: vi.fn(() => true),
  encryptString: vi.fn(),
  decryptString: vi.fn(),
}));

vi.mock("electron", () => ({
  dialog: { showMessageBox: electron.showMessageBox },
  safeStorage: {
    isEncryptionAvailable: electron.isEncryptionAvailable,
    encryptString: electron.encryptString,
    decryptString: electron.decryptString,
  },
}));

interface FileIdentity {
  sha256: string;
  size: number;
}

type FileSnapshot = Record<string, FileIdentity>;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
const GUARD_RELATIVE_PATH = "restore-control/active.guard";
const configuredBackend = process.env.JAP_RECOVERY_TEST_BACKEND;

async function fileIdentity(path: string): Promise<FileIdentity> {
  const hash = createHash("sha256");
  let size = 0;
  for await (const chunk of createReadStream(path)) {
    const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += value.length;
    hash.update(value);
  }
  return { sha256: hash.digest("hex"), size };
}

async function snapshotFiles(root: string): Promise<FileSnapshot> {
  const snapshot: FileSnapshot = {};

  async function visit(directory: string): Promise<void> {
    const entries = await readdir(directory, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const path = join(directory, entry.name);
      const info = await lstat(path);
      if (info.isSymbolicLink())
        throw new Error("The packaged recovery fixture contains a link.");
      if (info.isDirectory()) {
        await visit(path);
        continue;
      }
      if (!info.isFile())
        throw new Error(
          "The packaged recovery fixture contains a special file.",
        );
      const name = relative(root, path).split(sep).join("/");
      if (!name || name.startsWith("../") || isAbsolute(name))
        throw new Error(
          "The packaged recovery fixture escaped its owned root.",
        );
      snapshot[name] = await fileIdentity(path);
    }
  }

  await visit(root);
  return Object.fromEntries(
    Object.entries(snapshot).sort(([left], [right]) =>
      left.localeCompare(right),
    ),
  );
}

function withoutGuard(snapshot: FileSnapshot): FileSnapshot {
  return Object.fromEntries(
    Object.entries(snapshot).filter(([name]) => name !== GUARD_RELATIVE_PATH),
  );
}

async function assertOwnedTemporaryRoot(
  temporaryParent: string,
  ownedRoot: string,
): Promise<void> {
  const current = await realpath(ownedRoot);
  const child = relative(temporaryParent, current);
  if (
    current !== ownedRoot ||
    !child ||
    child === ".." ||
    child.startsWith(`..${sep}`) ||
    isAbsolute(child) ||
    resolve(current) === resolve(temporaryParent)
  )
    throw new Error(
      "Packaged recovery temporary-directory identity changed; it was preserved.",
    );
}

async function unusedLoopbackPort(): Promise<number> {
  const server = createServer();
  try {
    await new Promise<void>((resolveListen, rejectListen) => {
      server.once("error", rejectListen);
      server.listen(0, "127.0.0.1", resolveListen);
    });
    const address = server.address();
    if (address === null || typeof address === "string")
      throw new Error("Unable to reserve an isolated loopback port.");
    return address.port;
  } finally {
    if (server.listening)
      await new Promise<void>((resolveClose, rejectClose) =>
        server.close((error) => (error ? rejectClose(error) : resolveClose())),
      );
  }
}

async function installedResources(
  sourceExecutable: string,
  ownedRoot: string,
): Promise<{ executable: string; resourcesPath: string }> {
  const sourceBundle = dirname(sourceExecutable);
  const sourceResources = dirname(sourceBundle);
  if (
    basename(sourceBundle).toLowerCase() === "backend" &&
    basename(sourceResources).toLowerCase() === "resources"
  )
    return { executable: sourceExecutable, resourcesPath: sourceResources };

  // `package:backend` produces the same one-directory bundle before Electron
  // copies it under resources/backend. Stage a byte-identical package layout so
  // this opt-in can qualify that intermediate artifact locally as well.
  const resourcesPath = join(ownedRoot, "installed", "resources");
  const targetBundle = join(resourcesPath, "backend");
  await mkdir(resourcesPath, { recursive: true });
  await cp(sourceBundle, targetBundle, {
    recursive: true,
    force: false,
    errorOnExist: true,
  });
  const executable = await realpath(
    join(targetBundle, "job-apply-pro-backend.exe"),
  );
  expect(await snapshotFiles(targetBundle)).toEqual(
    await snapshotFiles(sourceBundle),
  );
  return { executable, resourcesPath: await realpath(resourcesPath) };
}

describe("delivered native restore recovery integration [opt-in: JAP_RECOVERY_TEST_BACKEND absolute executable]", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.clearAllMocks();
  });

  it.skipIf(configuredBackend === undefined)(
    "keeps cancel inert and finalizes authenticated terminal evidence without changing workspace bytes",
    async () => {
      if (process.platform !== "win32")
        throw new Error(
          "The delivered Windows restore recovery opt-in requires Windows.",
        );
      if (!configuredBackend || !isAbsolute(configuredBackend))
        throw new Error(
          "JAP_RECOVERY_TEST_BACKEND must name an absolute delivered backend executable.",
        );
      const sourceExecutable = await realpath(configuredBackend);
      if (
        basename(sourceExecutable) !== "job-apply-pro-backend.exe" ||
        !(await stat(sourceExecutable)).isFile()
      )
        throw new Error(
          "JAP_RECOVERY_TEST_BACKEND did not resolve to the packaged backend executable.",
        );

      const temporaryParent = await realpath(tmpdir());
      const ownedRoot = await realpath(
        await mkdtemp(join(temporaryParent, "job-apply-pro-recovery-")),
      );
      await assertOwnedTemporaryRoot(temporaryParent, ownedRoot);

      let supervisor: BackendSupervisor | undefined;
      let supervisorExitProven = false;
      let recoveryCommandUncertain = false;
      let primaryFailure: unknown;
      let cleanupFailure: unknown;
      try {
        const installed = await installedResources(sourceExecutable, ownedRoot);
        const workspacePath = join(ownedRoot, "workspace");
        await mkdir(workspacePath, { recursive: true });
        const dataRoot = await realpath(workspacePath);
        const documentRoot = join(dataRoot, "documents");
        const documentPath = join(documentRoot, "recovery-fixture.enc");
        const databasePath = join(dataRoot, "job-apply-pro.db");
        const masterKeyPath = join(dataRoot, "secrets", "master-key.bin");
        const databaseUrl = `sqlite:///${databasePath.replaceAll("\\", "/")}`;
        const masterKey = randomBytes(32).toString("base64");
        const protectedKey = randomBytes(48);

        // No workstation provider, path, Python, or Job Apply Pro setting is
        // inherited by the fixture. The supervisor adds only its explicit local
        // paths and credentials; recovery applies an even narrower environment.
        for (const name of Object.keys(process.env)) {
          const normalized = name.toUpperCase();
          if (
            normalized.startsWith("JAP_") ||
            normalized === "PYTHONPATH" ||
            normalized === "PYTHONHOME"
          )
            vi.stubEnv(name, undefined);
        }
        vi.stubEnv(
          "JAP_ENVIRONMENT",
          `packaged-recovery-${randomBytes(12).toString("hex")}`,
        );
        vi.stubEnv(
          "JAP_AI_CONFIG_JSON",
          JSON.stringify({ providers: [], models: [], policies: [] }),
        );
        vi.stubEnv(
          "JAP_COMMUNICATION_CONFIG_JSON",
          JSON.stringify({
            providers: [],
            oauth_clients: [],
            automatic_categories: [],
          }),
        );
        vi.stubEnv("JAP_AUTOMATION_ENABLED", "false");
        vi.stubEnv("JAP_SUPERVISED_PORTAL_ENABLED", "false");
        vi.stubEnv("JAP_SUPERVISED_FIELD_EXECUTION_ENABLED", "false");
        vi.stubEnv("JAP_SUPERVISED_PORTAL_SUBMISSION_ENABLED", "false");
        vi.stubEnv("JAP_BROWSER_HEADLESS", "true");

        const port = await unusedLoopbackPort();
        vi.stubEnv("JAP_API_HOST", "127.0.0.1");
        vi.stubEnv("JAP_API_PORT", String(port));

        supervisor = new BackendSupervisor({
          projectRoot: dataRoot,
          dataRoot,
          baseUrl: `http://127.0.0.1:${port}/api/v1`,
          apiToken: randomBytes(32).toString("base64url"),
          masterKey,
          databaseUrl,
          backendExecutable: installed.executable,
          browserEngine: "msedge",
        });

        await supervisor.start();
        await mkdir(documentRoot, { recursive: true });
        await writeFile(documentPath, "packaged-restore-source", {
          encoding: "utf8",
          flag: "wx",
        });
        const backup = await supervisor.client.createBackup(
          "Packaged native recovery fixture",
        );
        expect(backup.status).toBe("VERIFIED");
        const plan = await supervisor.client.stageRestore(backup.id);
        expect(plan.status).toBe("STAGED");
        await writeFile(documentPath, "packaged-pre-restore-bytes", "utf8");

        await supervisor.stop();
        expect(supervisor.status.state).toBe("stopped");
        await supervisor.applyOfflineRestore(plan.id, plan.fingerprint);
        expect(supervisor.status.state).toBe("ready");
        await supervisor.stop();
        expect(supervisor.status.state).toBe("stopped");

        const operationsRoot = join(dataRoot, "restore-control", "operations");
        const operationEntries = await readdir(operationsRoot, {
          withFileTypes: true,
        });
        expect(operationEntries).toHaveLength(1);
        expect(operationEntries[0]!.isDirectory()).toBe(true);
        const operationId = operationEntries[0]!.name;
        expect(operationId).toMatch(UUID_PATTERN);
        const operationRoot = await realpath(join(operationsRoot, operationId));
        expect(await readdir(operationRoot)).toEqual(
          expect.arrayContaining([
            "intent.v2.enc",
            "objects",
            "receipt.v2.enc",
          ]),
        );

        const guardPath = join(dataRoot, ...GUARD_RELATIVE_PATH.split("/"));
        await expect(lstat(guardPath)).rejects.toMatchObject({
          code: "ENOENT",
        });
        await writeFile(guardPath, operationId, {
          encoding: "ascii",
          flag: "wx",
          mode: 0o600,
        });
        await mkdir(dirname(masterKeyPath), { recursive: true });
        await writeFile(masterKeyPath, protectedKey, {
          flag: "wx",
          mode: 0o600,
        });

        electron.decryptString.mockImplementation((value: Buffer) => {
          expect(value).toEqual(protectedKey);
          return masterKey;
        });
        electron.showMessageBox.mockResolvedValue({
          response: 0,
          checkboxChecked: false,
        });
        const beforeCancel = await snapshotFiles(dataRoot);
        const operationBefore = await snapshotFiles(operationRoot);

        recoveryCommandUncertain = true;
        await expect(
          runInstalledRestoreRecovery({
            dataRoot,
            databaseUrl,
            projectRoot: installed.resourcesPath,
            resourcesPath: installed.resourcesPath,
            masterKeyPath,
          }),
        ).resolves.toBe("cancelled");
        recoveryCommandUncertain = false;

        expect(await snapshotFiles(dataRoot)).toEqual(beforeCancel);
        expect(await readFile(guardPath, "ascii")).toBe(operationId);
        expect(dialog.showMessageBox).toHaveBeenCalledExactlyOnceWith(
          expect.objectContaining({
            defaultId: 0,
            cancelId: 0,
            buttons: ["Keep workspace blocked", "Finalize exact restore state"],
          }),
        );

        electron.showMessageBox.mockReset();
        electron.showMessageBox
          .mockResolvedValueOnce({ response: 1, checkboxChecked: false })
          .mockResolvedValueOnce({ response: 0, checkboxChecked: false });
        recoveryCommandUncertain = true;
        await expect(
          runInstalledRestoreRecovery({
            dataRoot,
            databaseUrl,
            projectRoot: installed.resourcesPath,
            resourcesPath: installed.resourcesPath,
            masterKeyPath,
          }),
        ).resolves.toBe("finalized");
        recoveryCommandUncertain = false;

        await expect(lstat(guardPath)).rejects.toMatchObject({
          code: "ENOENT",
        });
        expect(await snapshotFiles(operationRoot)).toEqual(operationBefore);
        expect(await snapshotFiles(dataRoot)).toEqual(
          withoutGuard(beforeCancel),
        );
        expect(electron.showMessageBox).toHaveBeenCalledTimes(2);
        expect(electron.showMessageBox.mock.calls[0]![0]).toMatchObject({
          defaultId: 0,
          cancelId: 0,
          buttons: ["Keep workspace blocked", "Finalize exact restore state"],
        });
        expect(electron.showMessageBox.mock.calls[1]![0]).toMatchObject({
          title: "Job Apply Pro — restore finalization verified",
          buttons: ["Close Job Apply Pro"],
        });
        expect(safeStorage.decryptString).toHaveBeenCalledTimes(2);
        expect(safeStorage.encryptString).not.toHaveBeenCalled();

        await supervisor.shutdown();
        supervisorExitProven = true;
      } catch (error) {
        primaryFailure = error;
      } finally {
        if (!supervisorExitProven && supervisor !== undefined) {
          try {
            await supervisor.shutdown();
            supervisorExitProven = true;
          } catch (error) {
            cleanupFailure = error;
          }
        }
        if (supervisor === undefined) supervisorExitProven = true;

        if (supervisorExitProven && !recoveryCommandUncertain) {
          try {
            await assertOwnedTemporaryRoot(temporaryParent, ownedRoot);
            await rm(ownedRoot, {
              recursive: true,
              force: false,
              maxRetries: 3,
              retryDelay: 100,
            });
          } catch (error) {
            cleanupFailure ??= error;
          }
        }
        vi.unstubAllEnvs();
      }

      if (primaryFailure !== undefined || cleanupFailure !== undefined) {
        const preserved =
          !supervisorExitProven || recoveryCommandUncertain || cleanupFailure;
        throw new Error(
          preserved
            ? `Packaged recovery qualification failed or cleanup was unproved; synthetic evidence was preserved at ${ownedRoot}.`
            : "Packaged recovery qualification failed after all owned process exits were proved.",
          { cause: primaryFailure ?? cleanupFailure },
        );
      }
    },
    300_000,
  );
});
