import { randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import { safeStorage } from "electron";

export async function loadOrCreateMasterKey(path: string): Promise<string> {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error(
      "Operating-system encryption is unavailable for the local master key.",
    );
  }
  try {
    const protectedValue = await readFile(path);
    return safeStorage.decryptString(protectedValue);
  } catch (error) {
    if (
      typeof error !== "object" ||
      error === null ||
      !("code" in error) ||
      error.code !== "ENOENT"
    ) {
      throw error;
    }
  }

  const masterKey = randomBytes(32).toString("base64");
  const protectedValue = safeStorage.encryptString(masterKey);
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, protectedValue, { mode: 0o600, flag: "wx" });
  return masterKey;
}
