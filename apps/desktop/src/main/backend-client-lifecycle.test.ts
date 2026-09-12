import { afterEach, describe, expect, it, vi } from "vitest";

import { BackendClient } from "./backend-client.js";

describe("backend request lifecycle cancellation", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("forwards cancellation while preserving the remaining-time deadline", async () => {
    vi.useFakeTimers();
    const cancellation = new AbortController();
    let requestSignal: AbortSignal | null | undefined;
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      requestSignal = init.signal;
      return new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener(
          "abort",
          () => reject(new Error("synthetic abort")),
          { once: true },
        );
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new BackendClient(
      "http://127.0.0.1:8765/api/v1",
      "synthetic-token",
    );
    const request = client
      .runtimeStatus({ signal: cancellation.signal, timeoutMs: 37 })
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(36);
    expect(requestSignal?.aborted).toBe(false);
    cancellation.abort();
    expect(await request).toBeInstanceOf(Error);
    expect(requestSignal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("bounds response-body consumption and clears its timer on timeout", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => ({
        ok: true,
        json: () =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener(
              "abort",
              () => reject(new Error("synthetic timeout")),
              { once: true },
            );
          }),
      })),
    );
    const client = new BackendClient(
      "http://127.0.0.1:8765/api/v1",
      "synthetic-token",
    );
    const request = client
      .runtimeStatus({ timeoutMs: 23 })
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(23);
    expect(await request).toBeInstanceOf(Error);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears successful request timers and forwards backup cancellation", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => [] }));
    vi.stubGlobal("fetch", fetchMock);
    const cancellation = new AbortController();
    const client = new BackendClient(
      "http://127.0.0.1:8765/api/v1",
      "synthetic-token",
    );
    await client.runDueBackupSchedules(cancellation.signal);
    const [, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(init.signal?.aborted).toBe(false);
    cancellation.abort();
    expect(init.signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});
