import { open, writeFile } from "node:fs/promises";

import type {
  NotificationPersistentState,
  NotificationStateStore,
} from "./notification-manager.js";

const MAX_STATE_BYTES = 64 * 1024;
const MAX_DELIVERED_IDS = 500;

const defaultState: NotificationPersistentState = {
  native_enabled: false,
  delivered_ids: [],
};

export class FileNotificationStateStore implements NotificationStateStore {
  constructor(private readonly filePath: string) {}

  async load(): Promise<NotificationPersistentState> {
    try {
      const handle = await open(this.filePath, "r");
      let buffer: Buffer;
      try {
        const candidate = Buffer.alloc(MAX_STATE_BYTES + 1);
        const { bytesRead } = await handle.read(
          candidate,
          0,
          candidate.byteLength,
          0,
        );
        if (bytesRead > MAX_STATE_BYTES) return defaultState;
        buffer = candidate.subarray(0, bytesRead);
      } finally {
        await handle.close();
      }
      const parsed: unknown = JSON.parse(buffer.toString("utf8"));
      if (typeof parsed !== "object" || parsed === null) return defaultState;
      const enabled = Reflect.get(parsed, "native_enabled");
      const delivered = Reflect.get(parsed, "delivered_ids");
      if (typeof enabled !== "boolean" || !Array.isArray(delivered)) {
        return defaultState;
      }
      const deliveredIds = delivered.filter(
        (value): value is string =>
          typeof value === "string" && value.length > 0 && value.length <= 500,
      );
      if (deliveredIds.length !== delivered.length) return defaultState;
      return {
        native_enabled: enabled,
        delivered_ids: deliveredIds.slice(-MAX_DELIVERED_IDS),
      };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT")
        return defaultState;
      return defaultState;
    }
  }

  async save(state: NotificationPersistentState): Promise<void> {
    const serialized = `${JSON.stringify(
      {
        native_enabled: state.native_enabled,
        delivered_ids: state.delivered_ids.slice(-MAX_DELIVERED_IDS),
      },
      null,
      2,
    )}\n`;
    if (Buffer.byteLength(serialized, "utf8") > MAX_STATE_BYTES) {
      throw new Error("Notification state exceeded its storage limit.");
    }
    await writeFile(this.filePath, serialized, {
      encoding: "utf8",
      mode: 0o600,
    });
  }
}
