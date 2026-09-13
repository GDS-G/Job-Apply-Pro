import { randomBytes } from "node:crypto";
import { mkdir, open, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import { safeStorage } from "electron";

import {
  assertMasterKeyCreationAdmission,
  assertRestoreAdmission,
  MissingMasterKeyError,
  type RestoreAdmissionOptions,
} from "./restore-admission.js";

function isStoredMasterKey(value: string): boolean {
  if (!/^[A-Za-z0-9+/]{43}=$/u.test(value)) return false;
  const decoded = Buffer.from(value, "base64");
  return decoded.length === 32 && decoded.toString("base64") === value;
}

/**
 * Load the original OS-protected key for an already-blocked recovery session.
 * This path intentionally has no create fallback and never writes the key store.
 */
export async function loadExistingMasterKey(path: string): Promise<string> {
  if (!safeStorage.isEncryptionAvailable()) throw new MissingMasterKeyError();
  let protectedValue: Buffer | undefined;
  try {
    const handle = await open(path, "r");
    try {
      const info = await handle.stat();
      if (
        !info.isFile() ||
        info.nlink !== 1 ||
        info.size < 1 ||
        info.size > 65_536
      )
        throw new MissingMasterKeyError();
      protectedValue = Buffer.alloc(info.size);
      const { bytesRead } = await handle.read(
        protectedValue,
        0,
        protectedValue.length,
        0,
      );
      if (bytesRead !== info.size) throw new MissingMasterKeyError();
    } finally {
      await handle.close();
    }
    const masterKey = safeStorage.decryptString(protectedValue);
    if (!isStoredMasterKey(masterKey)) throw new MissingMasterKeyError();
    return masterKey;
  } catch {
    throw new MissingMasterKeyError();
  } finally {
    protectedValue?.fill(0);
  }
}

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
