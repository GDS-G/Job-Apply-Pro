import type { IpcMainInvokeEvent } from "electron";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  DocumentSelectionRequest,
  JobReadinessSnapshot,
  QualificationRequest,
  RequirementsRequest,
} from "@job-apply-pro/contracts";
import { BackendClient } from "./backend-client.js";
import { registerJobReadinessIpc } from "./job-readiness-ipc.js";

type Handler = (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown;
const { handlers, showMessageBox, exposeInMainWorld, rendererInvoke } =
  vi.hoisted(() => ({
    handlers: new Map<string, Handler>(),
    showMessageBox: vi.fn(),
    exposeInMainWorld: vi.fn(),
    rendererInvoke: vi.fn(),
  }));
vi.mock("electron", () => ({
  ipcMain: {
    handle: (name: string, listener: Handler) => handlers.set(name, listener),
  },
  BrowserWindow: { fromWebContents: () => undefined },
  dialog: { showMessageBox },
  contextBridge: { exposeInMainWorld },
  ipcRenderer: { invoke: rendererInvoke },
}));
const hash = "a".repeat(64);
const requirements: RequirementsRequest = {
  application_id: "app-1",
  source_fingerprint: hash,
  items: [{ span_id: "b".repeat(64), classification: "MANDATORY" }],
};
const qualification: QualificationRequest = {
  application_id: "app-1",
  requirements_review_id: "review-1",
  findings: [
    {
      requirement_id: "c".repeat(64),
      status: "SUPPORTED",
      claim_ids: ["claim-1"],
    },
  ],
};
const resume: DocumentSelectionRequest = {
  application_id: "app-1",
  kind: "RESUME",
  preferred_tags: ["cloud"],
  excluded_document_ids: [],
  prefer_primary: true,
};
const saved: JobReadinessSnapshot = {
  application_id: "app-1",
  profile_id: "profile-1",
  workflow_id: "workflow-1",
  job_id: "job-1",
  state: "DEDUPLICATED",
  supported: false,
  status: "UNSUPPORTED",
  source: null,
  source_fingerprint: null,
  spans: [],
  evidence_claims: [],
  requirements_review: null,
  qualification_review: null,
  selection_review: null,
  allowed_actions: [],
  notice: "Synthetic test result",
};
const approvalOperations = [
  {
    kind: "requirements",
    method: "approveJobRequirements",
    value: { input: requirements, review_fingerprint: hash },
    body: {
      ...requirements,
      review_fingerprint: hash,
      confirmation_phrase: "APPROVE REVIEWED REQUIREMENTS",
    },
  },
  {
    kind: "qualification",
    method: "approveJobQualification",
    value: {
      input: qualification,
      review_fingerprint: hash,
      approve_eligibility: false,
    },
    body: {
      ...qualification,
      review_fingerprint: hash,
      approve_eligibility: false,
      confirmation_phrase: "APPROVE REVIEWED QUALIFICATION",
    },
  },
  {
    kind: "resume",
    method: "approveJobResume",
    value: {
      input: resume,
      review_fingerprint: hash,
      document_version_id: "version-1",
    },
    body: {
      ...resume,
      review_fingerprint: hash,
      document_version_id: "version-1",
      confirmation_phrase: "SELECT REVIEWED DOCUMENT",
    },
  },
] as const;

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Job readiness native approval boundary", () => {
  const client = {
    getJobReadiness: vi.fn<BackendClient["getJobReadiness"]>(),
    previewJobRequirements: vi.fn<BackendClient["previewJobRequirements"]>(),
    approveJobRequirements: vi.fn<BackendClient["approveJobRequirements"]>(),
    previewJobQualification: vi.fn<BackendClient["previewJobQualification"]>(),
    approveJobQualification: vi.fn<BackendClient["approveJobQualification"]>(),
    previewJobResume: vi.fn<BackendClient["previewJobResume"]>(),
    approveJobResume: vi.fn<BackendClient["approveJobResume"]>(),
  };
  const invoke = async (channel: string, ...args: unknown[]) =>
    handlers.get(channel)!({ sender: {} } as IpcMainInvokeEvent, ...args);
  beforeEach(() => {
    handlers.clear();
    showMessageBox.mockReset().mockResolvedValue({ response: 0 });
    for (const method of Object.values(client)) method.mockReset();
    client.getJobReadiness.mockResolvedValue(saved);
    client.approveJobRequirements.mockResolvedValue(saved);
    client.approveJobQualification.mockResolvedValue(saved);
    client.approveJobResume.mockResolvedValue(saved);
    registerJobReadinessIpc(client);
  });
  function noRequests() {
    for (const method of Object.values(client))
      expect(method).not.toHaveBeenCalled();
  }

  it("exposes seven bounded local operations and no generic transition", async () => {
    expect([...handlers.keys()]).toEqual([
      "job-readiness:get",
      "job-readiness:requirements-preview",
      "job-readiness:qualification-preview",
      "job-readiness:resume-preview",
      "job-readiness:requirements-approve",
      "job-readiness:qualification-approve",
      "job-readiness:resume-approve",
    ]);
    await expect(invoke("job-readiness:get", "app-1")).resolves.toEqual(saved);
    await invoke("job-readiness:requirements-preview", requirements);
    await invoke("job-readiness:qualification-preview", qualification);
    await invoke("job-readiness:resume-preview", resume);
    expect(client.getJobReadiness).toHaveBeenCalledExactlyOnceWith("app-1");
    expect(client.previewJobRequirements).toHaveBeenCalledExactlyOnceWith(
      requirements,
    );
    expect(client.previewJobQualification).toHaveBeenCalledExactlyOnceWith(
      qualification,
    );
    expect(client.previewJobResume).toHaveBeenCalledExactlyOnceWith(resume);
    expect(showMessageBox).not.toHaveBeenCalled();
  });

  it.each(approvalOperations)(
    "requires cancel-default native confirmation for $kind approval",
    async ({ kind, method, value, body }) => {
      await expect(
        invoke(`job-readiness:${kind}-approve`, value),
      ).resolves.toBeNull();
      expect(client[method]).not.toHaveBeenCalled();
      expect(showMessageBox).toHaveBeenCalledWith(
        expect.objectContaining({
          defaultId: 0,
          cancelId: 0,
          buttons: ["Cancel", "Approve reviewed choice"],
          detail: expect.stringContaining("app-1"),
        }),
      );
      showMessageBox.mockResolvedValueOnce({ response: 1 });
      await expect(
        invoke(`job-readiness:${kind}-approve`, value),
      ).resolves.toEqual(saved);
      expect(client[method]).toHaveBeenCalledExactlyOnceWith(body);
    },
  );

  it("does not submit an approval while native review remains open", async () => {
    let resolve!: (value: { response: number }) => void;
    showMessageBox.mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const operation = invoke(
      "job-readiness:resume-approve",
      approvalOperations[2].value,
    );
    expect(client.approveJobResume).not.toHaveBeenCalled();
    resolve({ response: 1 });
    await operation;
    expect(client.approveJobResume).toHaveBeenCalledTimes(1);
  });

  it.each(approvalOperations)(
    "rejects renderer confirmation phrases, unexpected fields and extra arguments for $kind",
    async ({ kind, value }) => {
      for (const invalid of [
        null,
        [],
        { ...value, confirmation_phrase: "BYPASS" },
        { ...value, review_fingerprint: "A".repeat(64) },
        { ...value, review_fingerprint: `${hash}\n` },
        Object.assign(Object.create({ inherited: true }), value),
      ]) {
        await expect(
          invoke(`job-readiness:${kind}-approve`, invalid),
        ).rejects.toThrow(TypeError);
      }
      await expect(
        invoke(`job-readiness:${kind}-approve`, value, "extra"),
      ).rejects.toThrow(TypeError);
      expect(showMessageBox).not.toHaveBeenCalled();
      noRequests();
    },
  );

  it("rejects raw requirement text, forged or duplicate span IDs, oversized sets and invalid classification", async () => {
    for (const input of [
      { ...requirements, description: "injected" },
      { ...requirements, source_fingerprint: "bad" },
      {
        ...requirements,
        items: [{ ...requirements.items[0], text: "forged" }],
      },
      {
        ...requirements,
        items: [{ span_id: "not-a-hash", classification: "MANDATORY" }],
      },
      {
        ...requirements,
        items: [{ span_id: hash, classification: "REQUIRED" }],
      },
      {
        ...requirements,
        items: [requirements.items[0], requirements.items[0]],
      },
      { ...requirements, items: Array(101).fill(requirements.items[0]) },
    ])
      await expect(
        invoke("job-readiness:requirements-preview", input),
      ).rejects.toThrow(TypeError);
    noRequests();
  });

  it("requires supported and contradicted claims, and never permits links on an unknown finding", async () => {
    for (const finding of [
      { requirement_id: hash, status: "UNKNOWN", claim_ids: ["claim-1"] },
      { requirement_id: hash, status: "SUPPORTED", claim_ids: [] },
      { requirement_id: hash, status: "CONTRADICTED", claim_ids: [] },
      {
        requirement_id: hash,
        status: "SUPPORTED",
        claim_ids: ["claim-1", "claim-1"],
      },
      {
        requirement_id: hash,
        status: "SUPPORTED",
        claim_ids: Array(31).fill("claim-1"),
      },
      { requirement_id: hash, status: "SUPPORTED", claim_ids: ["../claim"] },
      {
        requirement_id: hash,
        status: "SUPPORTED",
        claim_ids: ["claim-1"],
        approved: true,
      },
    ])
      await expect(
        invoke("job-readiness:qualification-preview", {
          ...qualification,
          findings: [finding],
        }),
      ).rejects.toThrow(TypeError);
    await expect(
      invoke("job-readiness:qualification-approve", {
        ...approvalOperations[1].value,
        approve_eligibility: "true",
      }),
    ).rejects.toThrow(TypeError);
    noRequests();
  });

  it("rejects unsafe application IDs and invalid resume preferences before dispatch", async () => {
    for (const id of [
      "",
      "../app",
      "app/other",
      "app\n1",
      "a".repeat(101),
      1,
      null,
    ])
      await expect(invoke("job-readiness:get", id)).rejects.toThrow(TypeError);
    for (const input of [
      { ...resume, kind: "COVER_LETTER" },
      { ...resume, prefer_primary: 1 },
      { ...resume, preferred_tags: ["secret\ncontrol"] },
      { ...resume, excluded_document_ids: ["same", "same"] },
      { ...resume, preferred_tags: Array(31).fill("tag") },
    ])
      await expect(
        invoke("job-readiness:resume-preview", input),
      ).rejects.toThrow(TypeError);
    noRequests();
  });

  it("sanitizes backend errors without retrying or exposing private content", async () => {
    client.getJobReadiness.mockRejectedValue(
      new Error("secret candidate evidence"),
    );
    await expect(invoke("job-readiness:get", "app-1")).rejects.toThrow(
      "Reload its local evidence",
    );
    expect(client.getJobReadiness).toHaveBeenCalledTimes(1);
    showMessageBox.mockResolvedValueOnce({ response: 1 });
    client.approveJobRequirements.mockRejectedValue(
      new Error("private source body"),
    );
    await expect(
      invoke("job-readiness:requirements-approve", approvalOperations[0].value),
    ).rejects.toThrow("No application was submitted");
    expect(client.approveJobRequirements).toHaveBeenCalledTimes(1);
  });
});

describe("Job readiness fixed HTTP and preload routes", () => {
  it("uses only authenticated local application review paths and exact bodies", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(async () => Response.json(saved));
    vi.stubGlobal("fetch", fetchMock);
    const client = new BackendClient(
      "http://127.0.0.1:8765/api/v1",
      "synthetic-token",
    );
    await client.getJobReadiness("app-1");
    await client.previewJobRequirements(requirements);
    await client.previewJobQualification(qualification);
    await client.previewJobResume(resume);
    for (const operation of approvalOperations) {
      if (operation.kind === "requirements")
        await client.approveJobRequirements(operation.body);
      else if (operation.kind === "qualification")
        await client.approveJobQualification(operation.body);
      else await client.approveJobResume(operation.body);
    }
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(
      [
        "",
        "/requirements/preview",
        "/qualification/preview",
        "/resume/preview",
        "/requirements/approve",
        "/qualification/approve",
        "/resume/approve",
      ].map(
        (suffix) =>
          `http://127.0.0.1:8765/api/v1/applications/app-1/job-review${suffix}`,
      ),
    );
    expect(
      fetchMock.mock.calls.slice(1).map(([, options]) => options?.body),
    ).toEqual(
      [
        requirements,
        qualification,
        resume,
        ...approvalOperations.map((operation) => operation.body),
      ].map((body) => JSON.stringify(body)),
    );
    for (const [, options] of fetchMock.mock.calls)
      expect(options?.headers).toEqual({
        "Content-Type": "application/json",
        "X-Job-Apply-Pro-Token": "synthetic-token",
      });
  });

  it("exposes only fixed readiness bridge methods without automatic calls", async () => {
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
    const operations = [
      ["getJobReadiness", "get", "app-1"],
      ["previewJobRequirements", "requirements-preview", requirements],
      ["previewJobQualification", "qualification-preview", qualification],
      ["previewJobResume", "resume-preview", resume],
      ...approvalOperations.map((operation) => [
        operation.method,
        `${operation.kind}-approve`,
        operation.value,
      ]),
    ] as const;
    for (const [method, channel, value] of operations) {
      await exposed.workbench[method as string]!(value);
      expect(rendererInvoke).toHaveBeenLastCalledWith(
        `job-readiness:${channel}`,
        value,
      );
    }
    expect(exposed.workbench.request).toBeUndefined();
    expect(exposed.workbench.invoke).toBeUndefined();
  });
});
