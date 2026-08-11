import { open } from "node:fs/promises";

export const MAX_PROVIDER_CONFIGURATION_BYTES = 65_536;

export async function readProviderConfigurationFile(
  filePath: string,
): Promise<string> {
  const handle = await open(filePath, "r");
  try {
    const buffer = Buffer.alloc(MAX_PROVIDER_CONFIGURATION_BYTES + 1);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    if (bytesRead > MAX_PROVIDER_CONFIGURATION_BYTES) {
      throw new TypeError("Provider configuration must not exceed 64 KiB.");
    }
    return buffer
      .subarray(0, bytesRead)
      .toString("utf8")
      .replace(/^\uFEFF/, "");
  } finally {
    await handle.close();
  }
}
