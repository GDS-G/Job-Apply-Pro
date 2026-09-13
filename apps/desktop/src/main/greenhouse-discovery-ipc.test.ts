import type { IpcMainInvokeEvent } from "electron";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  GreenhouseImportResult,
  GreenhouseJobImportInput,
  GreenhouseJobList,
  GreenhouseJobListInput,
  GreenhouseJobReview,
  GreenhouseJobReviewInput,
} from "@job-apply-pro/contracts";

import { BackendApiError, BackendClient } from "./backend-client.js";
import { registerGreenhouseDiscoveryIpc } from "./greenhouse-discovery-ipc.js";

type Handler = (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown;
const { handlers, exposeInMainWorld, rendererInvoke } = vi.hoisted(() => ({
  handlers: new Map<string, Handler>(),
  exposeInMainWorld: vi.fn(),
  rendererInvoke: vi.fn(),
}));
vi.mock("electron", () => ({
  ipcMain: {
    handle: (channel: string, listener: Handler) =>
      handlers.set(channel, listener),
  },
  contextBridge: { exposeInMainWorld },
  ipcRenderer: { invoke: rendererInvoke },
}));

const listInput: GreenhouseJobListInput = { board_token: "Example_Board-1" };
const reviewInput: GreenhouseJobReviewInput = {
  ...listInput,
  posting_id: "9223372036854775807",
};
const importInput: GreenhouseJobImportInput = {
  ...reviewInput,
  review_fingerprint: "a".repeat(64),
  profile_id: "profile-1",
};
const listing: GreenhouseJobList = {
  ...listInput,
  board_name: "Example Board",
  fetched_at: "2026-09-12T12:00:00Z",
  jobs: [
    {
      posting_id: reviewInput.posting_id,
      title: "Engineer",
      location: null,
      source_url: null,
      navigation_supported: false,
    },
  ],
  excluded_prospect_count: 1,
};
const review: GreenhouseJobReview = {
  ...reviewInput,
  title: "Engineer",
  location: null,
  source_url: null,
  navigation_supported: false,
  employer: "Example Board",
  description: "A plain-text public posting.",
  api_url:
    "https://boards-api.greenhouse.io/v1/boards/Example_Board-1/jobs/9223372036854775807",
  reported_url: "https://careers.example.invalid/job/1",
  provider_updated_at: null,
  fetched_at: listing.fetched_at,
  normalizer_version: "greenhouse-v1",
  review_fingerprint: importInput.review_fingerprint,
  qualification_status: "NOT_EVALUATED",
};
const importResult: GreenhouseImportResult = {
  outcome: "STALE_REVIEW",
  job: null,
  workflow: null,
  notice: "Fetch a fresh review before importing.",
};
const operations = [
  {
    channel: "discovery:greenhouse-list",
    method: "listGreenhouseJobs",
    input: listInput,
    result: listing,
    error: "Greenhouse public listings are unavailable. Try again.",
  },
  {
    channel: "discovery:greenhouse-review",
    method: "reviewGreenhouseJob",
    input: reviewInput,
    result: review,
    error: "Greenhouse job review is unavailable. Fetch a fresh review.",
  },
  {
    channel: "discovery:greenhouse-import",
    method: "importGreenhouseJob",
    input: importInput,
    result: importResult,
    error:
      "Greenhouse local import could not be confirmed. Refresh local workflows before retrying. No application was submitted.",
  },
] as const;

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("Greenhouse discovery fixed HTTP routes", () => {
  it("posts exact request bodies only to authenticated local routes", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json(listing))
      .mockResolvedValueOnce(Response.json(review))
      .mockResolvedValueOnce(Response.json(importResult));
    vi.stubGlobal("fetch", fetchMock);
    const client = new BackendClient(
      "http://127.0.0.1:8765/api/v1",
      "synthetic-token",
    );
    await expect(client.listGreenhouseJobs(listInput)).resolves.toEqual(
      listing,
    );
    await expect(client.reviewGreenhouseJob(reviewInput)).resolves.toEqual(
      review,
    );
    await expect(client.importGreenhouseJob(importInput)).resolves.toEqual(
      importResult,
    );
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8765/api/v1/discovery/greenhouse/list",
      "http://127.0.0.1:8765/api/v1/discovery/greenhouse/review",
      "http://127.0.0.1:8765/api/v1/discovery/greenhouse/import",
    ]);
    expect(fetchMock.mock.calls.map(([, options]) => options?.body)).toEqual(
      [listInput, reviewInput, importInput].map((input) =>
        JSON.stringify(input),
      ),
    );
    for (const [, options] of fetchMock.mock.calls) {
      expect(options?.method).toBe("POST");
      expect(options?.headers).toEqual({
        "Content-Type": "application/json",
        "X-Job-Apply-Pro-Token": "synthetic-token",
      });
      expect(options?.signal?.aborted).toBe(false);
    }
  });

  it.each([
    {
      label: "listing",
      request: (client: BackendClient) => client.listGreenhouseJobs(listInput),
    },
    {
      label: "review",
      request: (client: BackendClient) =>
        client.reviewGreenhouseJob(reviewInput),
    },
    {
      label: "import",
      request: (client: BackendClient) =>
        client.importGreenhouseJob(importInput),
    },
  ])(
    "bounds $label response consumption to 30 seconds",
    async ({ request }) => {
      vi.useFakeTimers();
      let requestSignal: AbortSignal | null | undefined;
      vi.stubGlobal(
        "fetch",
        vi.fn(async (_url: string, init: RequestInit) => {
          requestSignal = init.signal;
          return {
            ok: true,
            json: () =>
              new Promise((_resolve, reject) => {
                init.signal?.addEventListener(
                  "abort",
                  () => reject(new Error("synthetic timeout")),
                  { once: true },
                );
              }),
          };
        }),
      );
      const client = new BackendClient(
        "http://127.0.0.1:8765/api/v1",
        "synthetic-token",
      );
      const pending = request(client).catch((error: unknown) => error);
      await vi.advanceTimersByTimeAsync(29_999);
      expect(requestSignal?.aborted).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      expect(await pending).toBeInstanceOf(Error);
      expect(requestSignal?.aborted).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
    },
  );
});

describe("Greenhouse discovery IPC boundary", () => {
  const client = {
    listGreenhouseJobs: vi.fn<BackendClient["listGreenhouseJobs"]>(),
    reviewGreenhouseJob: vi.fn<BackendClient["reviewGreenhouseJob"]>(),
    importGreenhouseJob: vi.fn<BackendClient["importGreenhouseJob"]>(),
  };
  async function invoke(channel: string, ...args: unknown[]) {
    return handlers.get(channel)!(
      { sender: {} } as IpcMainInvokeEvent,
      ...args,
    );
  }
  function expectNoRequests() {
    for (const method of Object.values(client)) {
      expect(method).not.toHaveBeenCalled();
    }
  }
  beforeEach(() => {
    handlers.clear();
    vi.resetAllMocks();
    client.listGreenhouseJobs.mockResolvedValue(listing);
    client.reviewGreenhouseJob.mockResolvedValue(review);
    client.importGreenhouseJob.mockResolvedValue(importResult);
    registerGreenhouseDiscoveryIpc(client);
  });

  it("registers exactly three fixed provider-specific channels", () => {
    expect([...handlers.keys()]).toEqual(
      operations.map(({ channel }) => channel),
    );
    expect(handlers.has("discovery:request")).toBe(false);
    expect(handlers.has("discovery:lever-list")).toBe(false);
    expectNoRequests();
  });

  it.each(operations)(
    "forwards only validated $method input",
    async (operation) => {
      await expect(invoke(operation.channel, operation.input)).resolves.toBe(
        operation.result,
      );
      expect(client[operation.method]).toHaveBeenCalledExactlyOnceWith(
        operation.input,
      );
      for (const other of operations) {
        if (other.method !== operation.method) {
          expect(client[other.method]).not.toHaveBeenCalled();
        }
      }
    },
  );

  it.each(operations)(
    "requires exactly one object for $method",
    async (operation) => {
      for (const args of [
        [],
        [undefined],
        [null],
        [[]],
        ["Example_Board-1"],
        [42],
        [true],
        [new Date()],
        [operation.input, undefined],
        [operation.input, { provider: "LEVER" }],
      ]) {
        await expect(invoke(operation.channel, ...args)).rejects.toThrow(
          TypeError,
        );
      }
      expectNoRequests();
    },
  );

  it.each(operations)(
    "requires the exact own key set for $method",
    async (operation) => {
      for (const key of Object.keys(operation.input)) {
        const missing: Record<string, unknown> = { ...operation.input };
        delete missing[key];
        await expect(invoke(operation.channel, missing)).rejects.toThrow(
          TypeError,
        );
      }
      for (const extra of [
        { provider: "LEVER" },
        { url: "https://untrusted.invalid/jobs" },
        { method: "DELETE" },
        { headers: { Authorization: "secret" } },
        { title: "Renderer-authored job" },
        { description: "Renderer-authored job" },
        { source_url: "file:///candidate-data" },
        { [Symbol("unexpected")]: true },
      ]) {
        await expect(
          invoke(operation.channel, { ...operation.input, ...extra }),
        ).rejects.toThrow(TypeError);
      }
      await expect(
        invoke(operation.channel, Object.create(operation.input)),
      ).rejects.toThrow(TypeError);
      await expect(
        invoke(
          operation.channel,
          Object.defineProperty({ ...operation.input }, "hidden", {
            value: true,
          }),
        ),
      ).rejects.toThrow(TypeError);
      expectNoRequests();
    },
  );

  it.each(operations)(
    "rejects invalid and reserved board tokens for $method",
    async (operation) => {
      for (const board_token of [
        null,
        123,
        "",
        " ",
        " internal",
        "internal",
        "INTERNAL",
        "InTeRnAl",
        "-board",
        "_board",
        "board/path",
        "board?token=secret",
        "https://boards.greenhouse.io/example",
        "example.invalid",
        "a".repeat(101),
        "board\n",
        "board\u0000",
        "böard",
      ]) {
        await expect(
          invoke(operation.channel, { ...operation.input, board_token }),
        ).rejects.toThrow(TypeError);
      }
      expectNoRequests();
    },
  );

  it("preserves valid board token case and accepts its exact length limits", async () => {
    for (const board_token of ["A", "A".repeat(100), "Internal_Board-1"]) {
      await invoke("discovery:greenhouse-list", { board_token });
      expect(client.listGreenhouseJobs).toHaveBeenLastCalledWith({
        board_token,
      });
    }
  });

  it.each(operations.slice(1))(
    "requires canonical signed-64 decimal posting ids for $method",
    async (operation) => {
      for (const posting_id of [
        null,
        1,
        1n,
        "",
        "0",
        "01",
        "+1",
        "-1",
        "1.0",
        "1e3",
        " 1",
        "1 ",
        "1\n",
        "1/2",
        "9223372036854775808",
        "9999999999999999999",
        "10000000000000000000",
      ]) {
        await expect(
          invoke(operation.channel, { ...operation.input, posting_id }),
        ).rejects.toThrow(TypeError);
      }
      expectNoRequests();
      for (const posting_id of ["1", "9223372036854775807"]) {
        await invoke(operation.channel, { ...operation.input, posting_id });
        expect(client[operation.method]).toHaveBeenLastCalledWith({
          ...operation.input,
          posting_id,
        });
      }
    },
  );

  it("requires an exact lowercase SHA-256 review fingerprint", async () => {
    for (const review_fingerprint of [
      null,
      123,
      "",
      "a".repeat(63),
      "a".repeat(65),
      "A".repeat(64),
      "g".repeat(64),
      `${"a".repeat(64)}\n`,
    ]) {
      await expect(
        invoke("discovery:greenhouse-import", {
          ...importInput,
          review_fingerprint,
        }),
      ).rejects.toThrow(TypeError);
    }
    expectNoRequests();
  });

  it("requires a bounded nonblank control-free profile id", async () => {
    for (const profile_id of [
      null,
      1,
      "",
      " ",
      "p".repeat(101),
      " profile-1",
      "profile-1 ",
      "profile\n1",
      "profile\u00001",
      "profile\u007f1",
      "profile\u00851",
    ]) {
      await expect(
        invoke("discovery:greenhouse-import", { ...importInput, profile_id }),
      ).rejects.toThrow(TypeError);
    }
    expectNoRequests();
    for (const profile_id of ["p", "p".repeat(100)]) {
      await invoke("discovery:greenhouse-import", {
        ...importInput,
        profile_id,
      });
      expect(client.importGreenhouseJob).toHaveBeenLastCalledWith({
        ...importInput,
        profile_id,
      });
    }
  });

  it.each(operations)(
    "sanitizes API and transport failures for $method",
    async (operation) => {
      for (const error of [
        new BackendApiError(
          "provider body https://secret.invalid private-token",
          502,
        ),
        new TypeError("transport failure private-token"),
        "raw provider body private-token",
      ]) {
        client[operation.method].mockRejectedValueOnce(error);
        await expect(
          invoke(operation.channel, operation.input),
        ).rejects.toThrow(new Error(operation.error));
      }
    },
  );
});

describe("Greenhouse discovery preload bridge", () => {
  it("exposes three narrow methods with fixed IPC channels", async () => {
    vi.resetModules();
    exposeInMainWorld.mockClear();
    rendererInvoke.mockReset();
    await import("../preload/index.js");
    const [name, exposed] = exposeInMainWorld.mock.calls[0] as [
      string,
      { workbench: Record<string, (input: unknown) => Promise<unknown>> },
    ];
    expect(name).toBe("jobApplyPro");
    expect(rendererInvoke).not.toHaveBeenCalled();
    for (const operation of operations) {
      rendererInvoke.mockResolvedValueOnce(operation.result);
      await expect(
        exposed.workbench[operation.method]!(operation.input),
      ).resolves.toBe(operation.result);
      expect(rendererInvoke).toHaveBeenLastCalledWith(
        operation.channel,
        operation.input,
      );
    }
    expect(exposed.workbench.request).toBeUndefined();
    expect(exposed.workbench.invoke).toBeUndefined();
  });
});
