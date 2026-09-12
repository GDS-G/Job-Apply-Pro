import type { IpcMainInvokeEvent } from "electron";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MediaCleanupListResponse } from "@job-apply-pro/contracts";

import { type BackendApiError, BackendClient } from "./backend-client.js";
import type { BackendSupervisor } from "./backend-supervisor.js";
import type { DesktopNotificationManager } from "./notification-manager.js";
import type { UpdateManager } from "./update-manager.js";
import { registerWorkbenchIpc } from "./workbench-ipc.js";

type IpcHandler = (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown;

const { handlers, handle } = vi.hoisted(() => {
  const handlers = new Map<string, IpcHandler>();
  return {
    handlers,
    handle: vi.fn((channel: string, listener: IpcHandler) => {
      handlers.set(channel, listener);
    }),
  };
});

vi.mock("electron", () => ({
  app: {},
  BrowserWindow: {},
  dialog: {},
  ipcMain: { handle },
  shell: {},
}));

const cleanupId = "2ac685a8-56c6-4ce1-b9ec-36b227940081";
const updatedAt = "2026-09-12T12:34:56.123456+00:00";
const confirmation = "I VERIFIED PROVIDER MEDIA CLEANUP";
const response: MediaCleanupListResponse = { items: [] };

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("media cleanup backend client", () => {
  const fetchMock = vi.fn<typeof fetch>();
  let client: BackendClient;

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(Response.json(response));
    vi.stubGlobal("fetch", fetchMock);
    client = new BackendClient("http://127.0.0.1:8765", "test-api-token");
  });

  it("lists cleanup records through the fixed authenticated GET route", async () => {
    await expect(client.listMediaCleanup()).resolves.toEqual(response);

    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      "http://127.0.0.1:8765/ai/media-cleanup",
      {
        headers: {
          "Content-Type": "application/json",
          "X-Job-Apply-Pro-Token": "test-api-token",
        },
        signal: expect.any(AbortSignal),
      },
    );
  });

  it("retries cleanup with one fixed POST and no upload or request body", async () => {
    await expect(client.retryMediaCleanup()).resolves.toEqual(response);

    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      "http://127.0.0.1:8765/ai/media-cleanup/retry",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Job-Apply-Pro-Token": "test-api-token",
        },
        signal: expect.any(AbortSignal),
      },
    );
  });

  it("posts the exact reviewed timestamp and confirmation to the resolve route", async () => {
    await expect(
      client.resolveMediaCleanup(cleanupId, updatedAt, confirmation),
    ).resolves.toEqual(response);

    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      `http://127.0.0.1:8765/ai/media-cleanup/${cleanupId}/resolve`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: updatedAt,
          confirmation,
        }),
        headers: {
          "Content-Type": "application/json",
          "X-Job-Apply-Pro-Token": "test-api-token",
        },
        signal: expect.any(AbortSignal),
      },
    );
  });

  it("encodes the id as one path segment, never as an arbitrary route", async () => {
    const untrustedId = "../../invoke?provider=example#upload";
    await client.resolveMediaCleanup(untrustedId, updatedAt, confirmation);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `http://127.0.0.1:8765/ai/media-cleanup/${encodeURIComponent(untrustedId)}/resolve`,
    );
  });

  it("preserves backend stale-review failures without further requests", async () => {
    fetchMock.mockResolvedValue(
      Response.json(
        { detail: "Cleanup record changed; refresh and review." },
        { status: 409 },
      ),
    );

    await expect(
      client.resolveMediaCleanup(cleanupId, updatedAt, confirmation),
    ).rejects.toMatchObject({
      name: "BackendApiError",
      status: 409,
      message: "Cleanup record changed; refresh and review.",
    } satisfies Partial<BackendApiError>);
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});

describe("media cleanup IPC boundary", () => {
  const client = {
    listMediaCleanup: vi.fn<BackendClient["listMediaCleanup"]>(),
    retryMediaCleanup: vi.fn<BackendClient["retryMediaCleanup"]>(),
    resolveMediaCleanup: vi.fn<BackendClient["resolveMediaCleanup"]>(),
  } satisfies Pick<
    BackendClient,
    "listMediaCleanup" | "retryMediaCleanup" | "resolveMediaCleanup"
  >;

  // Registration only closes over these dependencies. Keep untested services
  // inert, with typed public interfaces, without starting a backend or updater.
  const supervisor = { client } as unknown as BackendSupervisor;
  const updates = {
    check: vi.fn<UpdateManager["check"]>(),
    download: vi.fn<UpdateManager["download"]>(),
    install: vi.fn<UpdateManager["install"]>(),
  } satisfies Pick<UpdateManager, "check" | "download" | "install">;
  const notifications = {
    refresh: vi.fn<DesktopNotificationManager["refresh"]>(),
    setNativeEnabled: vi.fn<DesktopNotificationManager["setNativeEnabled"]>(),
  } satisfies Pick<DesktopNotificationManager, "refresh" | "setNativeEnabled">;

  async function invoke(channel: string, ...args: unknown[]): Promise<unknown> {
    const listener = handlers.get(channel);
    if (!listener) throw new Error(`Unregistered IPC channel: ${channel}`);
    return listener({} as IpcMainInvokeEvent, ...args);
  }

  function expectNoClientDispatch(): void {
    expect(client.listMediaCleanup).not.toHaveBeenCalled();
    expect(client.retryMediaCleanup).not.toHaveBeenCalled();
    expect(client.resolveMediaCleanup).not.toHaveBeenCalled();
  }

  beforeEach(() => {
    handlers.clear();
    vi.clearAllMocks();
    client.listMediaCleanup.mockResolvedValue(response);
    client.retryMediaCleanup.mockResolvedValue(response);
    client.resolveMediaCleanup.mockResolvedValue(response);
    registerWorkbenchIpc(
      supervisor,
      updates as unknown as UpdateManager,
      notifications as unknown as DesktopNotificationManager,
    );
  });

  it("registers only the three explicit cleanup channels", () => {
    expect(
      [...handlers.keys()].filter((channel) => channel.startsWith("ai:")),
    ).toEqual([
      "ai:media-cleanup-list",
      "ai:media-cleanup-retry",
      "ai:media-cleanup-resolve",
    ]);
    expectNoClientDispatch();
  });

  it.each([
    ["ai:media-cleanup-list", "listMediaCleanup"],
    ["ai:media-cleanup-retry", "retryMediaCleanup"],
  ] as const)("dispatches %s with no arguments", async (channel, method) => {
    await expect(invoke(channel)).resolves.toBe(response);
    expect(client[method]).toHaveBeenCalledExactlyOnceWith();
    expect(client.resolveMediaCleanup).not.toHaveBeenCalled();
  });

  it.each(["ai:media-cleanup-list", "ai:media-cleanup-retry"])(
    "rejects all supplied arguments on %s before dispatch",
    async (channel) => {
      for (const value of [
        undefined,
        null,
        "/ai/invoke",
        { path: "/ai/upload" },
      ]) {
        await expect(invoke(channel, value)).rejects.toThrow(TypeError);
      }
      expectNoClientDispatch();
    },
  );

  it.each([
    updatedAt,
    "2026-09-12T12:34:56Z",
    "2026-09-12T12:34:56.123-05:00",
    "2024-02-29T23:59:59+00:00",
  ])("passes the exact reviewed timestamp %s untouched", async (timestamp) => {
    await expect(
      invoke("ai:media-cleanup-resolve", cleanupId, timestamp, confirmation),
    ).resolves.toBe(response);
    expect(client.resolveMediaCleanup).toHaveBeenCalledExactlyOnceWith(
      cleanupId,
      timestamp,
      confirmation,
    );
    expect(client.listMediaCleanup).not.toHaveBeenCalled();
    expect(client.retryMediaCleanup).not.toHaveBeenCalled();
  });

  it.each([
    undefined,
    null,
    123,
    "",
    "not-a-uuid",
    cleanupId.replaceAll("-", ""),
    ` ${cleanupId}`,
    `${cleanupId} `,
    `${cleanupId}\n`,
    `{${cleanupId}}`,
    `${cleanupId}/../retry`,
    "https://example.invalid/ai/invoke",
  ])("rejects non-exact UUID %j before dispatch", async (id) => {
    await expect(
      invoke("ai:media-cleanup-resolve", id, updatedAt, confirmation),
    ).rejects.toThrow(TypeError);
    expectNoClientDispatch();
  });

  it.each([
    undefined,
    null,
    123,
    "",
    "invalid",
    "2026-09-12",
    "2026-09-12T12:34:56",
    "2026-09-12 12:34:56Z",
    "2026-02-30T12:34:56Z",
    "2026-02-29T12:34:56Z",
    "2026-13-12T12:34:56Z",
    "2026-09-12T24:00:00Z",
    "2026-09-12T12:60:00Z",
    "2026-09-12T12:34:56+24:00",
    "2026-09-12T12:34:56+00:60",
    ` ${updatedAt}`,
    `${updatedAt} `,
    `${updatedAt}\n`,
  ])(
    "rejects invalid or unzoned timestamp %j before dispatch",
    async (timestamp) => {
      await expect(
        invoke("ai:media-cleanup-resolve", cleanupId, timestamp, confirmation),
      ).rejects.toThrow(TypeError);
      expectNoClientDispatch();
    },
  );

  it.each([
    undefined,
    null,
    true,
    "",
    "CONFIRM",
    confirmation.toLowerCase(),
    ` ${confirmation}`,
    `${confirmation} `,
    `${confirmation}\n`,
  ])("rejects non-exact confirmation %j before dispatch", async (value) => {
    await expect(
      invoke("ai:media-cleanup-resolve", cleanupId, updatedAt, value),
    ).rejects.toThrow(TypeError);
    expectNoClientDispatch();
  });

  it("rejects missing and extra resolve arguments before dispatch", async () => {
    await expect(invoke("ai:media-cleanup-resolve")).rejects.toThrow(TypeError);
    await expect(
      invoke("ai:media-cleanup-resolve", cleanupId, updatedAt),
    ).rejects.toThrow(TypeError);
    await expect(
      invoke(
        "ai:media-cleanup-resolve",
        cleanupId,
        updatedAt,
        confirmation,
        "/ai/invoke",
      ),
    ).rejects.toThrow(TypeError);
    expectNoClientDispatch();
  });
});
