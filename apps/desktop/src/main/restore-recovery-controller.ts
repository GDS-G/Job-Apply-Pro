import { spawn } from "node:child_process";
import { open } from "node:fs/promises";
import { join, resolve } from "node:path";

import { dialog } from "electron";

import {
  restoreAdmissionBlocked,
  restoreAdmissionRoots,
  type RestoreAdmissionOptions,
} from "./restore-admission.js";
import { loadExistingMasterKey } from "./secret-store.js";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
const FINGERPRINT_PATTERN = /^[0-9a-f]{64}$/u;
const MAX_GUARD_BYTES = 36;
const MAX_STDOUT_BYTES = 32 * 1024;
const MAX_STDERR_BYTES = 8 * 1024;
const RECOVERY_COMMAND_TIMEOUT_MS = 60_000;

export const INSTALLED_RECOVERY_MESSAGE =
  "The authenticated restore recovery could not continue. The recovery guard remains in place and normal startup, migrations, API services, and updates remain blocked. Preserve the workspace, restore-control folder, backups, staging files, and original protected key before retrying.";

export class InstalledRecoveryError extends Error {
  constructor() {
    super(INSTALLED_RECOVERY_MESSAGE);
    this.name = "InstalledRecoveryError";
  }
}

export interface InstalledRecoveryOptions extends RestoreAdmissionOptions {
  resourcesPath: string;
  masterKeyPath: string;
}

export type InstalledRecoveryOutcome =
  "cancelled" | "finalized" | "resumed" | "rolled-back";

interface RestoreInspection {
  operation_id: string;
  version: 2;
  state:
    "INTERRUPTED" | "RESUMING" | "ROLLING_BACK" | "APPLIED" | "ROLLED_BACK";
  rollback_supported: boolean;
  review_fingerprint: string | null;
  resume_supported: boolean;
  resume_review_fingerprint: string | null;
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}

async function readGuardOperation(
  admission: RestoreAdmissionOptions,
): Promise<string> {
  if (!restoreAdmissionBlocked(admission)) throw new InstalledRecoveryError();
  const guards: string[] = [];
  for (const root of restoreAdmissionRoots(admission)) {
    const path = join(root, "restore-control", "active.guard");
    let handle;
    try {
      handle = await open(path, "r");
      const info = await handle.stat();
      if (
        !info.isFile() ||
        info.nlink !== 1 ||
        info.size < 1 ||
        info.size > MAX_GUARD_BYTES
      )
        throw new InstalledRecoveryError();
      const buffer = Buffer.alloc(MAX_GUARD_BYTES + 1);
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
      if (bytesRead !== info.size) throw new InstalledRecoveryError();
      const value = buffer.subarray(0, bytesRead).toString("ascii");
      if (!UUID_PATTERN.test(value)) throw new InstalledRecoveryError();
      guards.push(value);
    } catch (error) {
      if (!isMissing(error)) throw new InstalledRecoveryError();
    } finally {
      await handle?.close().catch(() => undefined);
    }
  }
  if (guards.length !== 1) throw new InstalledRecoveryError();
  return guards[0]!;
}

function recoveryEnvironment(
  options: InstalledRecoveryOptions,
  masterKey: string,
): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  for (const [name, value] of Object.entries(process.env)) {
    const normalized = name.toUpperCase();
    if (
      normalized.startsWith("JAP_") ||
      normalized === "PYTHONPATH" ||
      normalized === "PYTHONHOME"
    )
      continue;
    environment[name] = value;
  }
  environment.JAP_MASTER_KEY = masterKey;
  environment.JAP_DATABASE_URL = options.databaseUrl;
  environment.JAP_WORKSPACE_ROOT = resolve(options.dataRoot);
  environment.PYTHONUNBUFFERED = "1";
  return environment;
}

async function runRecoveryCommand(
  options: InstalledRecoveryOptions,
  masterKey: string,
  arguments_: readonly string[],
): Promise<Buffer> {
  const executable = join(
    resolve(options.resourcesPath),
    "backend",
    "job-apply-pro-backend.exe",
  );
  let child;
  try {
    child = spawn(executable, [...arguments_], {
      cwd: resolve(options.resourcesPath),
      env: recoveryEnvironment(options, masterKey),
      windowsHide: true,
      shell: false,
      detached: false,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch {
    throw new InstalledRecoveryError();
  }
  if (!child.stdout || !child.stderr) throw new InstalledRecoveryError();

  return await new Promise<Buffer>((resolveOutput, rejectOutput) => {
    const stdout: Buffer[] = [];
    let stdoutBytes = 0;
    let stderrBytes = 0;
    let oversized = false;
    let settled = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const reject = () => {
      if (settled) return;
      settled = true;
      if (timeout !== undefined) clearTimeout(timeout);
      rejectOutput(new InstalledRecoveryError());
    };
    timeout = setTimeout(() => {
      try {
        child.kill();
      } catch {
        // The recovery session still fails closed if termination is refused.
      } finally {
        reject();
      }
    }, RECOVERY_COMMAND_TIMEOUT_MS);
    timeout.unref();
    child.stdout.on("data", (chunk: Buffer | string) => {
      const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      stdoutBytes += value.length;
      if (stdoutBytes <= MAX_STDOUT_BYTES) stdout.push(value);
      else oversized = true;
    });
    child.stderr.on("data", (chunk: Buffer | string) => {
      stderrBytes += Buffer.byteLength(chunk);
      if (stderrBytes > MAX_STDERR_BYTES) oversized = true;
      // Drain without retaining private paths or backend diagnostics.
    });
    child.once("error", reject);
    child.once("close", (code, signal) => {
      if (settled) return;
      if (code !== 0 || signal !== null || oversized || stderrBytes !== 0) {
        reject();
        return;
      }
      settled = true;
      if (timeout !== undefined) clearTimeout(timeout);
      resolveOutput(Buffer.concat(stdout, stdoutBytes));
    });
  });
}

function parseInspection(
  output: Buffer,
  expectedOperation: string,
): RestoreInspection {
  if (output.length === 0 || output.length > MAX_STDOUT_BYTES)
    throw new InstalledRecoveryError();
  let value: unknown;
  try {
    value = JSON.parse(output.toString("utf8"));
  } catch {
    throw new InstalledRecoveryError();
  }
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new InstalledRecoveryError();
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  if (
    keys.join("\0") !==
    [
      "operation_id",
      "resume_review_fingerprint",
      "resume_supported",
      "review_fingerprint",
      "rollback_supported",
      "state",
      "version",
    ].join("\0")
  )
    throw new InstalledRecoveryError();
  const state = record.state;
  if (
    record.operation_id !== expectedOperation ||
    record.version !== 2 ||
    typeof state !== "string" ||
    ![
      "INTERRUPTED",
      "RESUMING",
      "ROLLING_BACK",
      "APPLIED",
      "ROLLED_BACK",
    ].includes(state) ||
    typeof record.rollback_supported !== "boolean" ||
    typeof record.resume_supported !== "boolean" ||
    !(
      record.review_fingerprint === null ||
      (typeof record.review_fingerprint === "string" &&
        FINGERPRINT_PATTERN.test(record.review_fingerprint))
    ) ||
    !(
      record.resume_review_fingerprint === null ||
      (typeof record.resume_review_fingerprint === "string" &&
        FINGERPRINT_PATTERN.test(record.resume_review_fingerprint))
    )
  )
    throw new InstalledRecoveryError();
  const supportsRollback = state === "INTERRUPTED" || state === "ROLLING_BACK";
  const supportsResume = state === "INTERRUPTED" || state === "RESUMING";
  if (
    record.rollback_supported !== supportsRollback ||
    record.resume_supported !== supportsResume ||
    (supportsRollback
      ? typeof record.review_fingerprint !== "string"
      : record.review_fingerprint !== null) ||
    (supportsResume
      ? typeof record.resume_review_fingerprint !== "string"
      : record.resume_review_fingerprint !== null)
  )
    throw new InstalledRecoveryError();
  return record as unknown as RestoreInspection;
}

async function inspect(
  options: InstalledRecoveryOptions,
  masterKey: string,
  operationId: string,
): Promise<RestoreInspection> {
  return parseInspection(
    await runRecoveryCommand(options, masterKey, [
      "restore-inspect",
      "--operation-id",
      operationId,
    ]),
    operationId,
  );
}

export async function runInstalledRestoreRecovery(
  options: InstalledRecoveryOptions,
): Promise<InstalledRecoveryOutcome> {
  const operationId = await readGuardOperation(options);
  const masterKey = await loadExistingMasterKey(options.masterKeyPath);
  const inspection = await inspect(options, masterKey, operationId);
  if (!inspection.rollback_supported && !inspection.resume_supported) {
    if (inspection.state !== "APPLIED" && inspection.state !== "ROLLED_BACK")
      throw new InstalledRecoveryError();
    const terminalState = inspection.state;
    const confirmation = await dialog.showMessageBox({
      type: "warning",
      title: "Job Apply Pro — verified restore finalization",
      message:
        terminalState === "APPLIED"
          ? "Finalize the verified applied restore?"
          : "Finalize the verified restore rollback?",
      detail:
        `Job Apply Pro authenticated terminal ${terminalState} receipt for operation ` +
        `${operationId}. Finalization rechecks every sealed target before clearing the ` +
        "recovery guard. It does not apply or roll back target files.",
      buttons: ["Keep workspace blocked", "Finalize exact restore state"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    if (confirmation.response !== 1) return "cancelled";

    const finalizeOutput = await runRecoveryCommand(options, masterKey, [
      "restore-finalize",
      "--operation-id",
      operationId,
    ]);
    if (finalizeOutput.length !== 0) throw new InstalledRecoveryError();
    const finalized = await inspect(options, masterKey, operationId);
    if (
      finalized.state !== terminalState ||
      finalized.rollback_supported ||
      finalized.review_fingerprint !== null ||
      restoreAdmissionBlocked(options)
    )
      throw new InstalledRecoveryError();

    await dialog.showMessageBox({
      type: "info",
      title: "Job Apply Pro — restore finalization verified",
      message: `The terminal ${terminalState} restore state was finalized and verified.`,
      detail:
        "Job Apply Pro will close now. Reopen it to start the recovered workspace normally.",
      buttons: ["Close Job Apply Pro"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    return "finalized";
  }
  const buttons = ["Keep workspace blocked"];
  const actions: ("ROLLBACK" | "RESUME")[] = [];
  if (inspection.rollback_supported) {
    buttons.push("Roll back exact restore");
    actions.push("ROLLBACK");
  }
  if (inspection.resume_supported) {
    buttons.push("Resume exact restore");
    actions.push("RESUME");
  }
  const confirmation = await dialog.showMessageBox({
    type: "warning",
    title: "Job Apply Pro — interrupted restore recovery",
    message: "Choose how to recover the interrupted restore.",
    detail:
      `Job Apply Pro authenticated interrupted operation ${operationId}. ` +
      "Rollback restores only its sealed before-images. Resume installs only its " +
      "sealed after-images; it does not reread staging files or merge later history. " +
      "Once either decision is recorded, it cannot be changed.\n\n" +
      `State: ${inspection.state}\n` +
      (inspection.review_fingerprint
        ? `Rollback fingerprint: ${inspection.review_fingerprint}\n`
        : "") +
      (inspection.resume_review_fingerprint
        ? `Resume fingerprint: ${inspection.resume_review_fingerprint}`
        : ""),
    buttons,
    defaultId: 0,
    cancelId: 0,
    noLink: true,
  });
  if (confirmation.response === 0) return "cancelled";
  const action = actions[confirmation.response - 1];
  if (!action) throw new InstalledRecoveryError();
  const fingerprint =
    action === "ROLLBACK"
      ? inspection.review_fingerprint
      : inspection.resume_review_fingerprint;
  if (!fingerprint) throw new InstalledRecoveryError();
  const command = action === "ROLLBACK" ? "restore-rollback" : "restore-resume";
  const recoveryOutput = await runRecoveryCommand(options, masterKey, [
    command,
    "--operation-id",
    operationId,
    "--fingerprint",
    fingerprint,
  ]);
  if (recoveryOutput.length !== 0) throw new InstalledRecoveryError();
  const terminal = await inspect(options, masterKey, operationId);
  const expectedState = action === "ROLLBACK" ? "ROLLED_BACK" : "APPLIED";
  if (
    terminal.state !== expectedState ||
    terminal.rollback_supported ||
    terminal.review_fingerprint !== null ||
    terminal.resume_supported ||
    terminal.resume_review_fingerprint !== null ||
    restoreAdmissionBlocked(options)
  )
    throw new InstalledRecoveryError();

  await dialog.showMessageBox({
    type: "info",
    title:
      action === "ROLLBACK"
        ? "Job Apply Pro — restore rollback verified"
        : "Job Apply Pro — restore resume verified",
    message:
      action === "ROLLBACK"
        ? "The interrupted restore was rolled back and verified."
        : "The interrupted restore was resumed and verified.",
    detail:
      "Job Apply Pro will close now. Reopen it to start the restored workspace normally.",
    buttons: ["Close Job Apply Pro"],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
  });
  return action === "ROLLBACK" ? "rolled-back" : "resumed";
}
