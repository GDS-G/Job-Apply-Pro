import type { IpcMainInvokeEvent } from "electron";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  GreenhouseApplicationLaunchPreview,
  GreenhouseFormActionPreview,
  SupervisedPortalRunSnapshot,
} from "@job-apply-pro/contracts";
import type { BackendClient } from "./backend-client.js";
import { registerGreenhouseApplicationIpc } from "./greenhouse-application-ipc.js";

type Handler = (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown;
const { handlers, showMessageBox } = vi.hoisted(() => ({
  handlers: new Map<string, Handler>(),
  showMessageBox: vi.fn(),
}));
vi.mock("electron", () => ({
  ipcMain: {
    handle: (name: string, listener: Handler) => handlers.set(name, listener),
  },
  BrowserWindow: { fromWebContents: () => undefined },
  dialog: { showMessageBox },
}));

const hash = "a".repeat(64);
const preview: GreenhouseApplicationLaunchPreview = {
  application_id: "app-1",
  workflow_id: "workflow-1",
  profile_id: "profile-1",
  job_id: "job-1",
  employer: "Synthetic Employer",
  title: "Platform Engineer",
  start_url: "https://job-boards.greenhouse.io/example/jobs/1",
  start_origin: "https://job-boards.greenhouse.io",
  selected_document_version_id: "version-1",
  source_fingerprint: "b".repeat(64),
  requirements_review_id: "requirements-1",
  qualification_review_id: "qualification-1",
  selection_review_id: "selection-1",
  policy_version: "reviewed-greenhouse-application-launch/1",
  review_fingerprint: hash,
  notice: "Synthetic reviewed launch.",
};
const run = {
  id: "run-1",
  portal: "GREENHOUSE",
  workflow_id: "workflow-1",
  browser_session_id: "browser-1",
  state: "AWAITING_USER",
  current_url: preview.start_url,
  allowed_origins: [preview.start_origin],
  page_fingerprint: "page-1",
  current_match: null,
  disposition: "USER_ACTION_REQUIRED",
  intervention_reasons: ["USER_TAKEOVER"],
  evidence: [],
  observed_controls: [],
  trace_path: null,
  created_at: "2026-09-14T12:00:00Z",
  updated_at: "2026-09-14T12:00:00Z",
} satisfies SupervisedPortalRunSnapshot;
const formReview = "d".repeat(64);
const formPreview = {
  application_id: "app-1",
  run_id: "run-1",
  action: "REVIEW_DOCUMENT_UPLOAD",
  control_key: "resume",
  form_review_fingerprint: formReview,
  workflow_id: "workflow-1",
  page_fingerprint: "greenhouse-document-page",
  page_type: "DOCUMENT_UPLOAD",
  stage: "DOCUMENTS",
  control_label: "Resume",
  selected_document_version_id: "version-1",
  selected_document_file_name: "candidate-resume.pdf",
  selected_document_sha256: "e".repeat(64),
  policy_version: "reviewed-greenhouse-form-action/1",
  preview_fingerprint: "f".repeat(64),
  notice: "Synthetic reviewed upload.",
} satisfies GreenhouseFormActionPreview;

describe("Reviewed Greenhouse native launch boundary", () => {
  const client = {
    previewGreenhouseApplicationLaunch:
      vi.fn<BackendClient["previewGreenhouseApplicationLaunch"]>(),
    startGreenhouseApplicationLaunch:
      vi.fn<BackendClient["startGreenhouseApplicationLaunch"]>(),
    previewGreenhouseFormAction:
      vi.fn<BackendClient["previewGreenhouseFormAction"]>(),
    executeGreenhouseFormAction:
      vi.fn<BackendClient["executeGreenhouseFormAction"]>(),
  };
  const invoke = async (channel: string, ...args: unknown[]) =>
    handlers.get(channel)!({ sender: {} } as IpcMainInvokeEvent, ...args);

  beforeEach(() => {
    handlers.clear();
    showMessageBox.mockReset().mockResolvedValue({ response: 0 });
    client.previewGreenhouseApplicationLaunch
      .mockReset()
      .mockResolvedValue(preview);
    client.startGreenhouseApplicationLaunch.mockReset().mockResolvedValue(run);
    client.previewGreenhouseFormAction
      .mockReset()
      .mockResolvedValue(formPreview);
    client.executeGreenhouseFormAction.mockReset().mockResolvedValue(run);
    registerGreenhouseApplicationIpc(client);
  });

  it("previews only by bounded application identity", async () => {
    await expect(
      invoke("greenhouse-application:preview", "app-1"),
    ).resolves.toEqual(preview);
    expect(
      client.previewGreenhouseApplicationLaunch,
    ).toHaveBeenCalledExactlyOnceWith("app-1");
    expect(showMessageBox).not.toHaveBeenCalled();
  });

  it("refetches review and requires cancel-default native confirmation", async () => {
    const input = {
      application_id: "app-1",
      review_fingerprint: hash,
      profile_name: "greenhouse-profile",
      engine: "msedge",
    };
    await expect(
      invoke("greenhouse-application:start", input),
    ).resolves.toBeNull();
    expect(client.previewGreenhouseApplicationLaunch).toHaveBeenCalledWith(
      "app-1",
    );
    expect(client.startGreenhouseApplicationLaunch).not.toHaveBeenCalled();
    expect(showMessageBox).toHaveBeenCalledWith(
      expect.objectContaining({
        defaultId: 0,
        cancelId: 0,
        buttons: ["Cancel", "Open reviewed application"],
        detail: expect.stringContaining(preview.start_origin),
      }),
    );
    showMessageBox.mockResolvedValueOnce({ response: 1 });
    await expect(
      invoke("greenhouse-application:start", input),
    ).resolves.toEqual(run);
    expect(
      client.startGreenhouseApplicationLaunch,
    ).toHaveBeenCalledExactlyOnceWith({
      ...input,
      confirmation_phrase: "OPEN REVIEWED GREENHOUSE APPLICATION",
    });
  });

  it("rejects renderer URLs, workflow IDs, phrases, malformed fingerprints and extra arguments", async () => {
    const base = {
      application_id: "app-1",
      review_fingerprint: hash,
      profile_name: "greenhouse-profile",
      engine: "msedge",
    };
    for (const value of [
      { ...base, start_url: "https://attacker.invalid" },
      { ...base, workflow_id: "other" },
      { ...base, confirmation_phrase: "BYPASS" },
      { ...base, review_fingerprint: "A".repeat(64) },
      { ...base, profile_name: "../profile" },
      { ...base, engine: "webkit" },
    ])
      await expect(
        invoke("greenhouse-application:start", value),
      ).rejects.toThrow(TypeError);
    await expect(
      invoke("greenhouse-application:start", base, "extra"),
    ).rejects.toThrow(TypeError);
    expect(showMessageBox).not.toHaveBeenCalled();
    expect(client.previewGreenhouseApplicationLaunch).not.toHaveBeenCalled();
    expect(client.startGreenhouseApplicationLaunch).not.toHaveBeenCalled();
  });

  it("refuses a fingerprint changed by the backend before opening native review", async () => {
    client.previewGreenhouseApplicationLaunch.mockResolvedValueOnce({
      ...preview,
      review_fingerprint: "c".repeat(64),
    });
    await expect(
      invoke("greenhouse-application:start", {
        application_id: "app-1",
        review_fingerprint: hash,
        profile_name: "greenhouse-profile",
        engine: "msedge",
      }),
    ).rejects.toThrow("changed");
    expect(showMessageBox).not.toHaveBeenCalled();
    expect(client.startGreenhouseApplicationLaunch).not.toHaveBeenCalled();
  });

  it("refetches an exact upload preview and requires cancel-default native review", async () => {
    const input = {
      application_id: "app-1",
      run_id: "run-1",
      action: "REVIEW_DOCUMENT_UPLOAD" as const,
      control_key: "resume",
      form_review_fingerprint: formReview,
    };
    await expect(
      invoke("greenhouse-form-action:execute", input),
    ).resolves.toBeNull();
    expect(client.previewGreenhouseFormAction).toHaveBeenCalledExactlyOnceWith(
      input,
    );
    expect(client.executeGreenhouseFormAction).not.toHaveBeenCalled();
    expect(showMessageBox).toHaveBeenCalledWith(
      expect.objectContaining({
        defaultId: 0,
        cancelId: 0,
        buttons: ["Cancel", "Upload reviewed document"],
        detail: expect.stringContaining("candidate-resume.pdf"),
      }),
    );

    showMessageBox.mockResolvedValueOnce({ response: 1 });
    await expect(
      invoke("greenhouse-form-action:execute", input),
    ).resolves.toEqual(run);
    expect(client.executeGreenhouseFormAction).toHaveBeenCalledExactlyOnceWith({
      ...input,
      preview_fingerprint: formPreview.preview_fingerprint,
      confirmation_phrase: "UPLOAD REVIEWED GREENHOUSE DOCUMENT",
    });
  });

  it("uses the distinct reviewed navigation confirmation without document fields", async () => {
    const navigation = {
      ...formPreview,
      action: "REVIEW_NAVIGATION" as const,
      control_key: "next",
      control_label: "Next",
      stage: "APPLICATION" as const,
      page_type: "APPLICATION_FORM",
      selected_document_version_id: null,
      selected_document_file_name: null,
      selected_document_sha256: null,
    };
    client.previewGreenhouseFormAction.mockResolvedValueOnce(navigation);
    showMessageBox.mockResolvedValueOnce({ response: 1 });
    const input = {
      application_id: "app-1",
      run_id: "run-1",
      action: "REVIEW_NAVIGATION" as const,
      control_key: "next",
      form_review_fingerprint: formReview,
    };

    await expect(
      invoke("greenhouse-form-action:execute", input),
    ).resolves.toEqual(run);
    expect(showMessageBox).toHaveBeenCalledWith(
      expect.objectContaining({
        buttons: ["Cancel", "Advance reviewed form"],
        detail: expect.stringContaining("It cannot submit the application"),
      }),
    );
    expect(client.executeGreenhouseFormAction).toHaveBeenCalledWith({
      ...input,
      preview_fingerprint: navigation.preview_fingerprint,
      confirmation_phrase: "ADVANCE REVIEWED GREENHOUSE FORM",
    });
  });

  it("rejects incomplete or cross-action backend previews before native review", async () => {
    const input = {
      application_id: "app-1",
      run_id: "run-1",
      action: "REVIEW_DOCUMENT_UPLOAD" as const,
      control_key: "resume",
      form_review_fingerprint: formReview,
    };
    for (const changed of [
      { policy_version: "untrusted-policy" },
      { preview_fingerprint: "F".repeat(64) },
      { selected_document_sha256: null },
      { selected_document_file_name: "C:/candidate-resume.pdf" },
    ]) {
      client.previewGreenhouseFormAction.mockResolvedValueOnce({
        ...formPreview,
        ...changed,
      } as GreenhouseFormActionPreview);
      await expect(
        invoke("greenhouse-form-action:execute", input),
      ).rejects.toThrow("changed");
    }
    expect(showMessageBox).not.toHaveBeenCalled();
    expect(client.executeGreenhouseFormAction).not.toHaveBeenCalled();
  });

  it("rejects malformed or over-broad renderer form action inputs before backend review", async () => {
    const base = {
      application_id: "app-1",
      run_id: "run-1",
      action: "REVIEW_NAVIGATION",
      control_key: "next",
      form_review_fingerprint: formReview,
    };
    for (const value of [
      { ...base, action: "FINAL_SUBMISSION_GATE" },
      { ...base, control_key: "../next" },
      { ...base, form_review_fingerprint: "D".repeat(64) },
      { ...base, locator: "button" },
      { ...base, confirmation_phrase: "BYPASS" },
    ])
      await expect(
        invoke("greenhouse-form-action:execute", value),
      ).rejects.toThrow(TypeError);
    await expect(
      invoke("greenhouse-form-action:execute", base, "extra"),
    ).rejects.toThrow(TypeError);
    expect(client.previewGreenhouseFormAction).not.toHaveBeenCalled();
    expect(client.executeGreenhouseFormAction).not.toHaveBeenCalled();
    expect(showMessageBox).not.toHaveBeenCalled();
  });
});
