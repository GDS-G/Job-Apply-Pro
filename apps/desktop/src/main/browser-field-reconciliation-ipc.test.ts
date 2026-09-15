import type { IpcMainInvokeEvent } from "electron";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BrowserFieldReconciliationPreview,
  BrowserFieldReconciliationResult,
  BrowserNavigationReconciliationPreview,
  BrowserNavigationReconciliationResult,
  BrowserSubmissionReconciliationPreview,
  BrowserSubmissionReconciliationResult,
  BrowserUploadReconciliationPreview,
  BrowserUploadReconciliationResult,
  BrowserProfileCleanupPreview,
  BrowserProfileCleanupResult,
  BrowserProfileRetirementPreview,
  BrowserProfileRetirementResult,
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
const cleanupId = "d1c5770b-22b0-4e97-81ee-722f9d9ad947";
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
const navigationPreview: BrowserNavigationReconciliationPreview = {
  operation_id: operationId,
  attempt_id: attemptId,
  session_id: sessionId,
  source_page_type: "APPLICATION_FORM",
  result_page_type: "DOCUMENT_UPLOAD",
  result_page_fingerprint: "greenhouse-documents-v2",
  review_fingerprint: "d".repeat(64),
  notice: "A recognized later Greenhouse form stage is visible.",
};
const navigationResult: BrowserNavigationReconciliationResult = {
  operation_id: operationId,
  attempt_id: attemptId,
  session_id: sessionId,
  source_page_type: navigationPreview.source_page_type,
  result_page_type: navigationPreview.result_page_type,
  result_page_fingerprint: navigationPreview.result_page_fingerprint,
  reconciliation_kind: "BROWSER_NAVIGATION_CONFIRMED",
  reconciled_at: "2026-09-15T19:00:00+00:00",
  notice: "Reviewed navigation was recorded without retrying it.",
};
const uploadPreview: BrowserUploadReconciliationPreview = {
  operation_id: operationId,
  attempt_id: attemptId,
  session_id: sessionId,
  file_name: "candidate-resume.pdf",
  page_type: "DOCUMENT_UPLOAD",
  result_page_fingerprint: "greenhouse-documents-uploaded-v2",
  review_fingerprint: "e".repeat(64),
  notice: "The exact reviewed filename is visible on the same form stage.",
};
const uploadResult: BrowserUploadReconciliationResult = {
  operation_id: operationId,
  attempt_id: attemptId,
  session_id: sessionId,
  file_name: uploadPreview.file_name,
  page_type: uploadPreview.page_type,
  result_page_fingerprint: uploadPreview.result_page_fingerprint,
  reconciliation_kind: "BROWSER_UPLOAD_CONFIRMED",
  reconciled_at: "2026-09-15T20:00:00+00:00",
  notice: "Reviewed file selection was recorded without uploading again.",
};
const submissionPreview: BrowserSubmissionReconciliationPreview = {
  operation_id: operationId,
  attempt_id: attemptId,
  session_id: sessionId,
  source_page_type: "SUBMISSION_REVIEW",
  result_page_type: "CONFIRMATION",
  result_page_fingerprint: "greenhouse-confirmation-v2",
  review_fingerprint: "f".repeat(64),
  notice: "An identifier-backed Greenhouse confirmation is visible.",
};
const submissionResult: BrowserSubmissionReconciliationResult = {
  operation_id: operationId,
  attempt_id: attemptId,
  session_id: sessionId,
  source_page_type: submissionPreview.source_page_type,
  result_page_type: submissionPreview.result_page_type,
  result_page_fingerprint: submissionPreview.result_page_fingerprint,
  reconciliation_kind: "BROWSER_SUBMISSION_CONFIRMED",
  reconciled_at: "2026-09-15T21:00:00+00:00",
  notice: "Confirmed submission was recorded without submitting again.",
};
const retirementPreview: BrowserProfileRetirementPreview = {
  engine: "msedge",
  profile_name: "workday-tenant-a",
  state: "AVAILABLE",
  allowed_origins: ["https://tenant.wd5.myworkdayjobs.com"],
  session_count: 2,
  last_used_at: "2026-09-15T18:00:00+00:00",
  pending_cleanup_id: null,
  file_count: 12,
  directory_count: 4,
  total_bytes: 4096,
  review_fingerprint: "b".repeat(64),
  notice: "Review local browser profile retirement.",
};
const retirementResult: BrowserProfileRetirementResult = {
  engine: "msedge",
  profile_name: "workday-tenant-a",
  removed: true,
  retired_at: "2026-09-15T18:05:00+00:00",
  notice: "Local browser profile data was removed.",
};
const cleanupPreview: BrowserProfileCleanupPreview = {
  ...retirementPreview,
  state: "CLEANUP_PENDING",
  pending_cleanup_id: cleanupId,
  cleanup_id: cleanupId,
  file_count: 7,
  directory_count: 3,
  total_bytes: 2048,
  review_fingerprint: "c".repeat(64),
  notice: "Review isolated browser profile cleanup.",
};
const cleanupResult: BrowserProfileCleanupResult = {
  engine: "msedge",
  profile_name: "workday-tenant-a",
  cleanup_id: cleanupId,
  removed: true,
  cleaned_at: "2026-09-15T18:06:00+00:00",
  notice: "Isolated local browser profile data was removed.",
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

  it("previews and approves reviewed navigation through its separate routes", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json(navigationPreview))
      .mockResolvedValueOnce(Response.json(navigationResult));

    await expect(
      client.previewBrowserNavigationReconciliation(operationId, sessionId),
    ).resolves.toEqual(navigationPreview);
    await expect(
      client.approveBrowserNavigationReconciliation(navigationPreview),
    ).resolves.toEqual(navigationResult);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `http://127.0.0.1:8765/browser/sessions/${sessionId}/navigation-reconciliations/${operationId}/preview`,
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      `http://127.0.0.1:8765/browser/sessions/${sessionId}/navigation-reconciliations/${operationId}/approve`,
    );
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        operation_id: operationId,
        expected_review_fingerprint: "d".repeat(64),
        confirmation_phrase: "RECONCILE REVIEWED NAVIGATION",
      }),
    });
  });

  it("previews and approves reviewed upload evidence through its separate routes", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json(uploadPreview))
      .mockResolvedValueOnce(Response.json(uploadResult));

    await expect(
      client.previewBrowserUploadReconciliation(operationId, sessionId),
    ).resolves.toEqual(uploadPreview);
    await expect(
      client.approveBrowserUploadReconciliation(uploadPreview),
    ).resolves.toEqual(uploadResult);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `http://127.0.0.1:8765/browser/sessions/${sessionId}/upload-reconciliations/${operationId}/preview`,
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      `http://127.0.0.1:8765/browser/sessions/${sessionId}/upload-reconciliations/${operationId}/approve`,
    );
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        operation_id: operationId,
        expected_review_fingerprint: "e".repeat(64),
        confirmation_phrase: "RECONCILE REVIEWED UPLOAD",
      }),
    });
  });

  it("previews and approves identifier-backed submission evidence through separate routes", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json(submissionPreview))
      .mockResolvedValueOnce(Response.json(submissionResult));

    await expect(
      client.previewBrowserSubmissionReconciliation(operationId, sessionId),
    ).resolves.toEqual(submissionPreview);
    await expect(
      client.approveBrowserSubmissionReconciliation(submissionPreview),
    ).resolves.toEqual(submissionResult);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `http://127.0.0.1:8765/browser/sessions/${sessionId}/submission-reconciliations/${operationId}/preview`,
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      `http://127.0.0.1:8765/browser/sessions/${sessionId}/submission-reconciliations/${operationId}/approve`,
    );
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        operation_id: operationId,
        expected_review_fingerprint: "f".repeat(64),
        confirmation_phrase: "RECONCILE CONFIRMED SUBMISSION",
      }),
    });
  });

  it("lists and reviews browser profiles through authenticated routes", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json([retirementPreview]))
      .mockResolvedValueOnce(Response.json(retirementPreview));

    await expect(client.listBrowserProfiles()).resolves.toEqual([
      retirementPreview,
    ]);
    await expect(
      client.previewBrowserProfileRetirement("msedge", "workday-tenant-a"),
    ).resolves.toEqual(retirementPreview);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "http://127.0.0.1:8765/browser/profiles",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "http://127.0.0.1:8765/browser/profiles/msedge/workday-tenant-a/retirement/preview",
    );
  });

  it("approves profile retirement only with the backend preview", async () => {
    fetchMock.mockResolvedValue(Response.json(retirementResult));

    await expect(
      client.approveBrowserProfileRetirement(retirementPreview),
    ).resolves.toEqual(retirementResult);

    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      "http://127.0.0.1:8765/browser/profiles/msedge/workday-tenant-a/retirement/approve",
      {
        method: "POST",
        body: JSON.stringify({
          engine: "msedge",
          profile_name: "workday-tenant-a",
          expected_review_fingerprint: "b".repeat(64),
          confirmation_phrase: "RETIRE LOCAL BROWSER PROFILE",
        }),
        headers: {
          "Content-Type": "application/json",
          "X-Job-Apply-Pro-Token": "test-api-token",
        },
        signal: expect.any(AbortSignal),
      },
    );
  });

  it("previews and approves only the exact isolated profile cleanup", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json(cleanupPreview))
      .mockResolvedValueOnce(Response.json(cleanupResult));

    await expect(
      client.previewBrowserProfileCleanup(
        "msedge",
        "workday-tenant-a",
        cleanupId,
      ),
    ).resolves.toEqual(cleanupPreview);
    await expect(
      client.approveBrowserProfileCleanup(cleanupPreview),
    ).resolves.toEqual(cleanupResult);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `http://127.0.0.1:8765/browser/profiles/msedge/workday-tenant-a/cleanups/${cleanupId}/preview`,
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      `http://127.0.0.1:8765/browser/profiles/msedge/workday-tenant-a/cleanups/${cleanupId}/approve`,
    );
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        engine: "msedge",
        profile_name: "workday-tenant-a",
        cleanup_id: cleanupId,
        expected_review_fingerprint: "c".repeat(64),
        confirmation_phrase: "REMOVE ISOLATED PROFILE DATA",
      }),
    });
  });
});

describe("browser field reconciliation IPC boundary", () => {
  const client = {
    previewBrowserFieldReconciliation:
      vi.fn<BackendClient["previewBrowserFieldReconciliation"]>(),
    approveBrowserFieldReconciliation:
      vi.fn<BackendClient["approveBrowserFieldReconciliation"]>(),
    previewBrowserNavigationReconciliation:
      vi.fn<BackendClient["previewBrowserNavigationReconciliation"]>(),
    approveBrowserNavigationReconciliation:
      vi.fn<BackendClient["approveBrowserNavigationReconciliation"]>(),
    previewBrowserUploadReconciliation:
      vi.fn<BackendClient["previewBrowserUploadReconciliation"]>(),
    approveBrowserUploadReconciliation:
      vi.fn<BackendClient["approveBrowserUploadReconciliation"]>(),
    previewBrowserSubmissionReconciliation:
      vi.fn<BackendClient["previewBrowserSubmissionReconciliation"]>(),
    approveBrowserSubmissionReconciliation:
      vi.fn<BackendClient["approveBrowserSubmissionReconciliation"]>(),
    listBrowserProfiles: vi.fn<BackendClient["listBrowserProfiles"]>(),
    previewBrowserProfileRetirement:
      vi.fn<BackendClient["previewBrowserProfileRetirement"]>(),
    approveBrowserProfileRetirement:
      vi.fn<BackendClient["approveBrowserProfileRetirement"]>(),
    previewBrowserProfileCleanup:
      vi.fn<BackendClient["previewBrowserProfileCleanup"]>(),
    approveBrowserProfileCleanup:
      vi.fn<BackendClient["approveBrowserProfileCleanup"]>(),
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

  async function invokeNavigation(...args: unknown[]): Promise<unknown> {
    const listener = handlers.get("workbench:reconcile-browser-navigation");
    if (!listener)
      throw new Error(
        "Browser navigation reconciliation IPC was not registered",
      );
    return listener({ sender } as IpcMainInvokeEvent, ...args);
  }

  async function invokeUpload(...args: unknown[]): Promise<unknown> {
    const listener = handlers.get("workbench:reconcile-browser-upload");
    if (!listener)
      throw new Error("Browser upload reconciliation IPC was not registered");
    return listener({ sender } as IpcMainInvokeEvent, ...args);
  }

  async function invokeSubmission(...args: unknown[]): Promise<unknown> {
    const listener = handlers.get("workbench:reconcile-browser-submission");
    if (!listener)
      throw new Error(
        "Browser submission reconciliation IPC was not registered",
      );
    return listener({ sender } as IpcMainInvokeEvent, ...args);
  }

  beforeEach(() => {
    handlers.clear();
    vi.clearAllMocks();
    fromWebContents.mockReturnValue(null);
    showMessageBox.mockResolvedValue({ response: 0 });
    client.previewBrowserFieldReconciliation.mockResolvedValue(preview);
    client.approveBrowserFieldReconciliation.mockResolvedValue(result);
    client.previewBrowserNavigationReconciliation.mockResolvedValue(
      navigationPreview,
    );
    client.approveBrowserNavigationReconciliation.mockResolvedValue(
      navigationResult,
    );
    client.previewBrowserUploadReconciliation.mockResolvedValue(uploadPreview);
    client.approveBrowserUploadReconciliation.mockResolvedValue(uploadResult);
    client.previewBrowserSubmissionReconciliation.mockResolvedValue(
      submissionPreview,
    );
    client.approveBrowserSubmissionReconciliation.mockResolvedValue(
      submissionResult,
    );
    client.listBrowserProfiles.mockResolvedValue([retirementPreview]);
    client.previewBrowserProfileRetirement.mockResolvedValue(retirementPreview);
    client.approveBrowserProfileRetirement.mockResolvedValue(retirementResult);
    client.previewBrowserProfileCleanup.mockResolvedValue(cleanupPreview);
    client.approveBrowserProfileCleanup.mockResolvedValue(cleanupResult);
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

  it("keeps uncertain navigation unresolved when the native warning is canceled", async () => {
    await expect(invokeNavigation(operationId, sessionId)).resolves.toBeNull();

    expect(
      client.previewBrowserNavigationReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(operationId, sessionId);
    expect(showMessageBox.mock.calls[0]?.[0]).toMatchObject({
      buttons: ["Cancel", "Record navigation outcome"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    expect(
      client.approveBrowserNavigationReconciliation,
    ).not.toHaveBeenCalled();
  });

  it("approves only the immutable navigation preview after explicit choice", async () => {
    showMessageBox.mockResolvedValue({ response: 1 });

    await expect(invokeNavigation(operationId, sessionId)).resolves.toEqual(
      navigationResult,
    );

    expect(
      client.previewBrowserNavigationReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(operationId, sessionId);
    expect(
      client.approveBrowserNavigationReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(navigationPreview);
  });

  it("rejects malformed upload reconciliation identifiers before any review", async () => {
    await expect(invokeUpload("../../other-route", sessionId)).rejects.toThrow(
      "External effect id must be a UUID.",
    );
    await expect(invokeUpload(operationId, "not-a-session")).rejects.toThrow(
      "Browser session id must be a UUID.",
    );

    expect(client.previewBrowserUploadReconciliation).not.toHaveBeenCalled();
    expect(showMessageBox).not.toHaveBeenCalled();
    expect(client.approveBrowserUploadReconciliation).not.toHaveBeenCalled();
  });

  it("keeps an uncertain upload unresolved when the cancel-default warning is canceled", async () => {
    await expect(invokeUpload(operationId, sessionId)).resolves.toBeNull();

    expect(
      client.previewBrowserUploadReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(operationId, sessionId);
    expect(showMessageBox.mock.calls[0]?.[0]).toMatchObject({
      buttons: ["Cancel", "Record upload outcome"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
      detail: expect.stringContaining("does not upload again"),
    });
    expect(showMessageBox.mock.calls[0]?.[0]).toMatchObject({
      detail: expect.stringContaining("prove provider receipt"),
    });
    expect(client.approveBrowserUploadReconciliation).not.toHaveBeenCalled();
  });

  it("approves only the immutable upload preview after explicit choice", async () => {
    showMessageBox.mockResolvedValue({ response: 1 });

    await expect(invokeUpload(operationId, sessionId)).resolves.toEqual(
      uploadResult,
    );

    expect(
      client.previewBrowserUploadReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(operationId, sessionId);
    expect(
      client.approveBrowserUploadReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(uploadPreview);
  });

  it("keeps an uncertain submission unresolved when native review is canceled", async () => {
    await expect(invokeSubmission(operationId, sessionId)).resolves.toBeNull();

    expect(
      client.previewBrowserSubmissionReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(operationId, sessionId);
    expect(showMessageBox.mock.calls[0]?.[0]).toMatchObject({
      buttons: ["Cancel", "Record confirmed submission"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
      detail: expect.stringContaining(
        "does not click, retry, upload, or submit again",
      ),
    });
    expect(
      client.approveBrowserSubmissionReconciliation,
    ).not.toHaveBeenCalled();
  });

  it("approves only the immutable submission preview after explicit choice", async () => {
    showMessageBox.mockResolvedValue({ response: 1 });

    await expect(invokeSubmission(operationId, sessionId)).resolves.toEqual(
      submissionResult,
    );

    expect(
      client.previewBrowserSubmissionReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(operationId, sessionId);
    expect(
      client.approveBrowserSubmissionReconciliation,
    ).toHaveBeenCalledExactlyOnceWith(submissionPreview);
  });

  it("validates profile retirement input before preview or dialog", async () => {
    const listener = handlers.get("workbench:retire-browser-profile");
    if (!listener) throw new Error("Profile retirement IPC was not registered");

    await expect(
      listener({ sender } as IpcMainInvokeEvent, "firefox", "profile"),
    ).rejects.toThrow("Browser profile engine is invalid.");
    await expect(
      listener({ sender } as IpcMainInvokeEvent, "msedge", "../profile"),
    ).rejects.toThrow("Browser profile name is invalid.");

    expect(client.previewBrowserProfileRetirement).not.toHaveBeenCalled();
    expect(showMessageBox).not.toHaveBeenCalled();
  });

  it("keeps profile data when the cancel-default warning is canceled", async () => {
    const listener = handlers.get("workbench:retire-browser-profile");
    if (!listener) throw new Error("Profile retirement IPC was not registered");

    await expect(
      listener({ sender } as IpcMainInvokeEvent, "msedge", "workday-tenant-a"),
    ).resolves.toBeNull();

    expect(showMessageBox.mock.calls[0]?.[0]).toMatchObject({
      buttons: ["Cancel", "Retire local profile"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    expect(client.approveBrowserProfileRetirement).not.toHaveBeenCalled();
  });

  it("retires only the immutable preview after explicit native approval", async () => {
    const listener = handlers.get("workbench:retire-browser-profile");
    if (!listener) throw new Error("Profile retirement IPC was not registered");
    showMessageBox.mockResolvedValue({ response: 1 });

    await expect(
      listener({ sender } as IpcMainInvokeEvent, "msedge", "workday-tenant-a"),
    ).resolves.toEqual(retirementResult);

    expect(
      client.previewBrowserProfileRetirement,
    ).toHaveBeenCalledExactlyOnceWith("msedge", "workday-tenant-a");
    expect(
      client.approveBrowserProfileRetirement,
    ).toHaveBeenCalledExactlyOnceWith(retirementPreview);
  });

  it("validates cleanup identity and defaults the cleanup warning to cancel", async () => {
    const listener = handlers.get("workbench:cleanup-browser-profile");
    if (!listener) throw new Error("Profile cleanup IPC was not registered");

    await expect(
      listener(
        { sender } as IpcMainInvokeEvent,
        "msedge",
        "workday-tenant-a",
        "not-a-uuid",
      ),
    ).rejects.toThrow("Browser profile cleanup id must be a UUID.");
    expect(client.previewBrowserProfileCleanup).not.toHaveBeenCalled();
    expect(showMessageBox).not.toHaveBeenCalled();

    await expect(
      listener(
        { sender } as IpcMainInvokeEvent,
        "msedge",
        "workday-tenant-a",
        cleanupId,
      ),
    ).resolves.toBeNull();
    expect(client.previewBrowserProfileCleanup).toHaveBeenCalledExactlyOnceWith(
      "msedge",
      "workday-tenant-a",
      cleanupId,
    );
    expect(showMessageBox.mock.calls[0]?.[0]).toMatchObject({
      buttons: ["Cancel", "Remove isolated data"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    expect(client.approveBrowserProfileCleanup).not.toHaveBeenCalled();
  });

  it("removes only the immutable isolated cleanup after native approval", async () => {
    const listener = handlers.get("workbench:cleanup-browser-profile");
    if (!listener) throw new Error("Profile cleanup IPC was not registered");
    showMessageBox.mockResolvedValue({ response: 1 });

    await expect(
      listener(
        { sender } as IpcMainInvokeEvent,
        "msedge",
        "workday-tenant-a",
        cleanupId,
      ),
    ).resolves.toEqual(cleanupResult);
    expect(client.approveBrowserProfileCleanup).toHaveBeenCalledExactlyOnceWith(
      cleanupPreview,
    );
  });
});
