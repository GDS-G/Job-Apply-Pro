import { ipcMain } from "electron";

import type {
  GreenhouseJobImportInput,
  GreenhouseJobListInput,
  GreenhouseJobReviewInput,
} from "@job-apply-pro/contracts";

import type { BackendClient } from "./backend-client.js";

function exactInput(
  args: unknown[],
  keys: readonly string[],
): Record<string, unknown> {
  const value = args[0];
  if (
    args.length !== 1 ||
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  ) {
    throw new TypeError("Greenhouse discovery input is invalid.");
  }
  const actualKeys = Reflect.ownKeys(value);
  if (
    actualKeys.length !== keys.length ||
    actualKeys.some((key) => typeof key !== "string" || !keys.includes(key))
  ) {
    throw new TypeError("Greenhouse discovery input is invalid.");
  }
  return value as Record<string, unknown>;
}

function boardToken(value: unknown): string {
  if (
    typeof value !== "string" ||
    value !== value.trim() ||
    !/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/.test(value) ||
    value.toLowerCase() === "internal"
  ) {
    throw new TypeError("Greenhouse board token is invalid.");
  }
  return value;
}

function postingId(value: unknown): string {
  if (
    typeof value !== "string" ||
    value !== value.trim() ||
    !/^[1-9][0-9]{0,18}$/.test(value) ||
    BigInt(value) > 9_223_372_036_854_775_807n
  ) {
    throw new TypeError("Greenhouse posting id is invalid.");
  }
  return value;
}

function reviewFingerprint(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length !== 64 ||
    !/^[a-f0-9]{64}$/.test(value)
  ) {
    throw new TypeError("Greenhouse review fingerprint is invalid.");
  }
  return value;
}

function profileId(value: unknown): string {
  if (
    typeof value !== "string" ||
    !value.trim() ||
    value !== value.trim() ||
    value.length > 100 ||
    [...value].some((character) => {
      const code = character.charCodeAt(0);
      return code < 32 || (code >= 127 && code <= 159);
    })
  ) {
    throw new TypeError("Greenhouse import profile id is invalid.");
  }
  return value;
}

export function registerGreenhouseDiscoveryIpc(
  client: Pick<
    BackendClient,
    "listGreenhouseJobs" | "reviewGreenhouseJob" | "importGreenhouseJob"
  >,
): void {
  ipcMain.handle("discovery:greenhouse-list", async (_event, ...args) => {
    const value = exactInput(args, ["board_token"]);
    const input: GreenhouseJobListInput = {
      board_token: boardToken(value.board_token),
    };
    try {
      return await client.listGreenhouseJobs(input);
    } catch {
      throw new Error("Greenhouse public listings are unavailable. Try again.");
    }
  });
  ipcMain.handle("discovery:greenhouse-review", async (_event, ...args) => {
    const value = exactInput(args, ["board_token", "posting_id"]);
    const input: GreenhouseJobReviewInput = {
      board_token: boardToken(value.board_token),
      posting_id: postingId(value.posting_id),
    };
    try {
      return await client.reviewGreenhouseJob(input);
    } catch {
      throw new Error(
        "Greenhouse job review is unavailable. Fetch a fresh review.",
      );
    }
  });
  ipcMain.handle("discovery:greenhouse-import", async (_event, ...args) => {
    const value = exactInput(args, [
      "board_token",
      "posting_id",
      "review_fingerprint",
      "profile_id",
    ]);
    const input: GreenhouseJobImportInput = {
      board_token: boardToken(value.board_token),
      posting_id: postingId(value.posting_id),
      review_fingerprint: reviewFingerprint(value.review_fingerprint),
      profile_id: profileId(value.profile_id),
    };
    try {
      return await client.importGreenhouseJob(input);
    } catch {
      throw new Error(
        "Greenhouse local import could not be confirmed. Refresh local workflows before retrying. No application was submitted.",
      );
    }
  });
}
