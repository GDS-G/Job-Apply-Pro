import type { IpcMainInvokeEvent } from "electron";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BrowserFieldReconciliationPreview,
  BrowserFieldReconciliationResult,
} from "@job-apply-pro/contracts";

import { BackendClient } from "./backend-client.js";
import type { BackendSupervisor } from "./backend-supervisor.js";
import type { DesktopNotificationManager } from "./notification-manager.js";
import type { UpdateManager } from "./update-manager.js";
import { registerWorkbenchIpc } from "./workbench-ipc.js";

type IpcHandler = (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown;

const { handlers, handle, showMessageBox, fromWebContents } = vi.hoisted(() => {
  const handlers = new Map<string, IpcHandler>();
  return {
    handlers,
    handle: vi.fn((channel: string, listener: IpcHandler) => {
      handlers.set(channel, listener);
    }),
    showMessageBox: vi.fn(),
    fromWebContents: vi.fn(),
  };
});

vi.mock("electron", () => ({
  app: {},
  BrowserWindow: { fromWebContents },
  dialog: { showMessageBox },
  ipcMain: { handle },
  shell: {},
}));

const operationId = "64a4cc96-07d1-4a0e-8000-a74811a13c0e";
const attemptId = "19c70be6-ea1b-4c71-b668-d359f7ce4b06";
const sessionId = "5fdf419a-0771-4d75-99d2-c76ba2f89719";
const preview: BrowserFieldReconciliationPreview = {
  operation_id: operationId,
  attempt_id: attemptId,
  session_id: sessionId,
  action_kind: "FILL",
  verification_kind: "VALUE_EQUALS",
  page_fingerprint: "greenhouse:questionnaire:ab12cd34",
  review_fingerprint: "a".repeat(64),
  notice:
    "The prior field write is visible and may be recorded without retrying it.",
};
const result: BrowserFieldReconciliationResult = {
  operation_id: operationId,
  attempt_id: attemptId,
  session_id: sessionId,
  action_kind: "FILL",
  page_fingerprint: preview.page_fingerprint,
  reconciliation_kind: "BROWSER_FIELD_VALUE_CONFIRMED",
  reconciled_at: "2026-09-15T18:00:00+00:00",
  notice:
    "The verified field outcome was recorded without repeating the action.",
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("browser field reconciliation backend client", () => {
  const fetchMock = vi.fn<typeof fetch>();
  let client: BackendClient;

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    client = new BackendClient("http://127.0.0.1:8765", "test-api-token");
  });

  it("previews the exact operation and session through one authenticated POST", async () => {
    fetchMock.mockResolvedValue(Response.json(preview));

    await expect(
      client.previewBrowserFieldReconciliation(operationId, sessionId),
    ).resolves.toEqual(preview);

    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      `http://127.0.0.1:8765/browser/sessions/${sessionId}/field-reconciliations/${operationId}/preview`,
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

  it("approves only the previewed fingerprint and fixed confirmation phrase", async () => {
    fetchMock.mockResolvedValue(Response.json(result));

    await expect(
      client.approveBrowserFieldReconciliation(preview),
    ).resolves.toEqual(result);

    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      `http://127.0.0.1:8765/browser/sessions/${sessionId}/field-reconciliations/${operationId}/approve`,
      {
        method: "POST",
        body: JSON.stringify({
          operation_id: operationId,
          expected_review_fingerprint: preview.review_fingerprint,
          confirmation_phrase: "RECONCILE VERIFIED FIELD",
        }),
        headers: {
          "Content-Type": "application/json",
          "X-Job-Apply-Pro-Token": "test-api-token",
        },
        signal: expect.any(AbortSignal),
      },
    );
  });
});

describe("browser field reconciliation IPC boundary", () => {
  const client = {
    previewBrowserFieldReconciliation:
      vi.fn<BackendClient["previewBrowserFieldReconciliation"]>(),
    approveBrowserFieldReconciliation:
      vi.fn<BackendClient["approveBrowserFieldReconciliation"]>(),
  };
  const supervisor = { client } as unknown as BackendSupervisor;
  const updates = {} as UpdateManager;
  const notifications = {} as DesktopNotificationManager;
  const sender = {};

  async function invoke(...args: unknown[]): Promise<unknown> {
    const listener = handlers.get("workbench:reconcile-browser-field");
    if (!listener)
      throw new Error("Browser reconciliation IPC was not registered");
    return listener({ sender } as IpcMainInvokeEvent, ...args);
  }

  beforeEach(() => {
    handlers.clear();
    vi.clearAllMocks();
    fromWebContents.mockReturnValue(null);
    showMessageBox.mockResolvedValue({ response: 0 });
    client.previewBrowserFieldReconciliation.mockResolvedValue(preview);
    client.approveBrowserFieldReconciliation.mockResolvedValue(result);
    registerWorkbenchIpc(supervisor, updates, notifications);
  });

  it("rejects malformed identifiers before preview, dialog, or approval", async () => {
    await expect(invoke("../../other-route", sessionId)).rejects.toThrow(
      "External effect id must be a UUID.",
    );
    await expect(invoke(operationId, "not-a-session")).rejects.toThrow(
      "Browser session id must be a UUID.",
    );

    expect(client.previewBrowserFieldReconciliation).not.toHaveBeenCalled();
    expect(showMessageBox).not.toHaveBeenCalled();
    expect(client.approveBrowserFieldReconciliation).not.toHaveBeenCalled();
  });

  it("defaults to cancel and never approves when the user cancels", async () => {
    await expect(invoke(operationId, sessionId)).resolves.toBeNull();

    expect(
      client.previewBrowserFieldReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(operationId, sessionId);
    expect(showMessageBox).toHaveBeenCalledOnce();
    expect(showMessageBox.mock.calls[0]?.[0]).toMatchObject({
      buttons: ["Cancel", "Record verified outcome"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    expect(client.approveBrowserFieldReconciliation).not.toHaveBeenCalled();
  });

  it("approves the immutable preview only after the explicit warning choice", async () => {
    showMessageBox.mockResolvedValue({ response: 1 });

    await expect(invoke(operationId, sessionId)).resolves.toEqual(result);

    expect(
      client.previewBrowserFieldReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(operationId, sessionId);
    expect(
      client.approveBrowserFieldReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(preview);
  });
});
