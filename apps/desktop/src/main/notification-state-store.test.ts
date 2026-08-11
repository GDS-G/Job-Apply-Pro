import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { FileNotificationStateStore } from "./notification-state-store.js";

const temporaryDirectories: string[] = [];

async function temporaryStatePath(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "jap-notifications-"));
  temporaryDirectories.push(directory);
  return join(directory, "notification-state.json");
}

describe("notification state store", () => {
  afterEach(async () => {
    await Promise.all(
      temporaryDirectories
        .splice(0)
        .map((directory) => rm(directory, { recursive: true, force: true })),
    );
  });

  it("round-trips the opt-in and delivered identifiers", async () => {
    const path = await temporaryStatePath();
    const store = new FileNotificationStateStore(path);

    await store.save({
      native_enabled: true,
      delivered_ids: ["workflow:one:MFA_REQUIRED:0"],
    });

    await expect(store.load()).resolves.toEqual({
      native_enabled: true,
      delivered_ids: ["workflow:one:MFA_REQUIRED:0"],
    });
    expect(await readFile(path, "utf8")).not.toContain("password");
  });

  it("rejects oversized or malformed state without reading past the limit", async () => {
    const path = await temporaryStatePath();
    const store = new FileNotificationStateStore(path);
    await writeFile(path, Buffer.alloc(64 * 1024 + 1, "x"));

    await expect(store.load()).resolves.toEqual({
      native_enabled: false,
      delivered_ids: [],
    });

    await writeFile(path, '{"native_enabled":"yes"}');
    await expect(store.load()).resolves.toEqual({
      native_enabled: false,
      delivered_ids: [],
    });
  });
});
