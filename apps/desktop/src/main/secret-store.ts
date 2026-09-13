import { randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import { safeStorage } from "electron";

import {
  assertMasterKeyCreationAdmission,
  assertRestoreAdmission,
  type RestoreAdmissionOptions,
} from "./restore-admission.js";

export async function loadOrCreateMasterKey(
  path: string,
  admission: RestoreAdmissionOptions,
): Promise<string> {
  assertRestoreAdmission(admission);
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

  // Recheck after the asynchronous read, before generating a missing key.
  assertMasterKeyCreationAdmission(admission);
  const masterKey = randomBytes(32).toString("base64");
  const protectedValue = safeStorage.encryptString(masterKey);
  await mkdir(dirname(path), { recursive: true });
  assertMasterKeyCreationAdmission(admission);
  await writeFile(path, protectedValue, { mode: 0o600, flag: "wx" });
  return masterKey;
}
