import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  MAX_PROVIDER_CONFIGURATION_BYTES,
  readProviderConfigurationFile,
} from "./provider-configuration-file.js";

const directories: string[] = [];

afterEach(async () => {
  await Promise.all(
    directories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

describe("provider configuration file", () => {
  it("strips a UTF-8 BOM and never reads beyond the configured limit", async () => {
    const directory = await mkdtemp(
      join(tmpdir(), "job-apply-pro-provider-config-"),
    );
    directories.push(directory);
    const validPath = join(directory, "valid.json");
    await writeFile(validPath, '\uFEFF{"oauth_clients":[]}', "utf8");
    expect(await readProviderConfigurationFile(validPath)).toBe(
      '{"oauth_clients":[]}',
    );

    const oversizedPath = join(directory, "oversized.json");
    await writeFile(
      oversizedPath,
      Buffer.alloc(MAX_PROVIDER_CONFIGURATION_BYTES + 1, 120),
    );
    await expect(readProviderConfigurationFile(oversizedPath)).rejects.toThrow(
      "64 KiB",
    );
  });
});
