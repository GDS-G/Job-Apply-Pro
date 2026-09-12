import type { ChildProcess, SpawnOptions } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdtemp, realpath, rm, stat } from "node:fs/promises";
import { createServer } from "node:net";
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

import { afterEach, describe, expect, it, vi } from "vitest";

import { buildInfo } from "../../../../packages/contracts/src/index.js";
import { BackendSupervisor } from "./backend-supervisor.js";

interface CapturedChild {
  child: ChildProcess;
  command: string;
  args: readonly string[];
  hidden: boolean;
  exitObserved: boolean;
  creationFailed: boolean;
  code: number | null;
  signal: NodeJS.Signals | null;
}

const capture = vi.hoisted(() => ({ children: [] as CapturedChild[] }));

// Instrument the source supervisor's actual spawn boundary; do not replace the
// delivered executable, process implementation, arguments, environment, or IO.
vi.mock("node:child_process", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:child_process")>();
  const spawn = (
    command: string,
    args: readonly string[],
    options: SpawnOptions,
  ) => {
    const child = actual.spawn(command, args, options);
    const record: CapturedChild = {
      child,
      command,
      args: [...args],
      hidden: options.windowsHide === true,
      exitObserved: false,
      creationFailed: false,
      code: null,
      signal: null,
    };
    capture.children.push(record);
    child.once("exit", (code, signal) => {
      record.exitObserved = true;
      record.code = code;
      record.signal = signal;
    });
    child.on("error", () => {
      if (child.pid === undefined) record.creationFailed = true;
    });
    return child;
  };
  return { ...actual, spawn, default: { ...actual, spawn } };
});

async function unusedLoopbackPort(): Promise<number> {
  const server = createServer();
  try {
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
    const address = server.address();
    if (address === null || typeof address === "string")
      throw new Error("Unable to reserve an isolated loopback port.");
    return address.port;
  } finally {
    if (server.listening)
      await new Promise<void>((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve())),
      );
  }
}

function exitProven(record: CapturedChild): boolean {
  return record.exitObserved || record.creationFailed;
}

async function cleanupOwnedWorkspace(
  supervisor: BackendSupervisor | undefined,
  temporaryParent: string,
  ownedRoot: string,
): Promise<void> {
  let shutdownFailed = false;
  try {
    await supervisor?.shutdown();
  } catch {
    shutdownFailed = true;
  }
  const unconfirmed = capture.children.filter((record) => !exitProven(record));
  if (shutdownFailed || unconfirmed.length > 0) {
    // Never use image-name/process-tree kills or remove a live writer's data.
    const pids = unconfirmed
      .map((record) => record.child.pid ?? "unavailable")
      .join(", ");
    throw new Error(
      `Lifecycle cleanup did not prove all captured child exits. Temporary data preserved at ${ownedRoot}; unconfirmed owned process IDs: ${pids || "none"}.`,
    );
  }
  const currentRoot = await realpath(ownedRoot);
  if (
    currentRoot !== ownedRoot ||
    resolve(ownedRoot) === resolve(temporaryParent)
  ) {
    throw new Error(
      "Lifecycle temporary directory identity changed; it was preserved.",
    );
  }
  await rm(ownedRoot, {
    recursive: true,
    force: false,
    maxRetries: 3,
    retryDelay: 100,
  });
}

const configuredBackend = process.env.JAP_LIFECYCLE_TEST_BACKEND;

describe("delivered backend supervisor integration [opt-in: JAP_LIFECYCLE_TEST_BACKEND absolute executable]", () => {
  afterEach(() => vi.unstubAllEnvs());

  it.skipIf(configuredBackend === undefined)(
    "uses real owned migration/serve processes, proves stop, then restarts safely",
    async () => {
      if (process.platform !== "win32")
        throw new Error(
          "The delivered Windows backend lifecycle opt-in requires Windows.",
        );
      if (!configuredBackend || !isAbsolute(configuredBackend))
        throw new Error(
          "JAP_LIFECYCLE_TEST_BACKEND must explicitly name an absolute delivered backend executable.",
        );
      const executable = await realpath(configuredBackend);
      expect(basename(executable)).toBe("job-apply-pro-backend.exe");
      expect((await stat(executable)).isFile()).toBe(true);
      expect(basename(dirname(executable))).toBe("backend");
      expect(basename(dirname(dirname(executable)))).toBe("resources");

      capture.children.length = 0;
      const temporaryParent = await realpath(tmpdir());
      const temporaryRoot = await mkdtemp(
        join(temporaryParent, "job-apply-pro-lifecycle-"),
      );
      const ownedRoot = await realpath(temporaryRoot);
      const relativeRoot = relative(temporaryParent, ownedRoot);
      if (
        !relativeRoot ||
        relativeRoot.startsWith(`..${sep}`) ||
        relativeRoot === ".." ||
        isAbsolute(relativeRoot)
      ) {
        throw new Error(
          "Lifecycle temporary directory failed its containment check; it was preserved.",
        );
      }
      let supervisor: BackendSupervisor | undefined;
      try {
        // No workstation JAP configuration, .env file, provider account, or data
        // directory is inherited. The backend's working directory is this empty root.
        for (const name of Object.keys(process.env)) {
          if (name.startsWith("JAP_")) vi.stubEnv(name, undefined);
        }
        const port = await unusedLoopbackPort();
        const environment = `packaged-lifecycle-${randomBytes(12).toString("hex")}`;
        vi.stubEnv("JAP_API_HOST", "127.0.0.1");
        vi.stubEnv("JAP_API_PORT", String(port));
        vi.stubEnv("JAP_ENVIRONMENT", environment);
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
        const apiToken = randomBytes(32).toString("base64url");
        const baseUrl = `http://127.0.0.1:${port}/api/v1`;
        supervisor = new BackendSupervisor({
          projectRoot: ownedRoot,
          dataRoot: ownedRoot,
          baseUrl,
          apiToken,
          masterKey: randomBytes(32).toString("base64"),
          databaseUrl: `sqlite:///${join(ownedRoot, "lifecycle.db").replaceAll("\\", "/")}`,
          backendExecutable: executable,
          browserEngine: "msedge",
        });

        for (let cycle = 0; cycle < 2; cycle += 1) {
          const start = supervisor.start();
          expect(supervisor.start()).toBe(start);
          await start;
          expect(supervisor.status.state).toBe("ready");
          const owners = capture.children.slice(cycle * 2);
          expect(owners.map((record) => record.args)).toEqual([
            ["migrate"],
            ["serve"],
          ]);
          expect(
            owners.every(
              (record) => record.command === executable && record.hidden,
            ),
          ).toBe(true);
          expect(owners[0]!.exitObserved).toBe(true);
          expect(owners[0]!.code).toBe(0);
          expect(owners[1]!.exitObserved).toBe(false);
          await supervisor.client.runtimeStatus({ timeoutMs: 5_000 });
          const health = await fetch(`${baseUrl}/health`, {
            headers: { "X-Job-Apply-Pro-Token": apiToken },
            signal: AbortSignal.timeout(5_000),
          });
          expect(health.ok).toBe(true);
          expect(await health.json()).toMatchObject({
            status: "ok",
            service: "job-apply-pro-backend",
            environment,
            version: buildInfo.version,
            build: buildInfo.name,
          });
          const stop = supervisor.stop();
          expect(supervisor.stop()).toBe(stop);
          await stop;
          expect(supervisor.status.state).toBe("stopped");
          expect(owners.every((record) => record.exitObserved)).toBe(true);
        }
        expect(capture.children).toHaveLength(4);
      } finally {
        await cleanupOwnedWorkspace(supervisor, temporaryParent, ownedRoot);
      }
    },
    210_000,
  );
});
