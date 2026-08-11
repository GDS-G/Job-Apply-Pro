import { dialog, ipcMain } from "electron";

import type {
  CandidateProfileCreate,
  MockWorkflowCreate,
  ReferencePortalRunCreate,
  WorkflowControlAction,
} from "@job-apply-pro/contracts";

import type { BackendSupervisor } from "./backend-supervisor.js";

const actions = new Set<WorkflowControlAction>([
  "ADVANCE",
  "PAUSE",
  "RESUME",
  "RETRY",
  "TAKEOVER",
  "STOP",
]);

function requiredText(value: unknown, name: string, maxLength: number): string {
  if (
    typeof value !== "string" ||
    value.trim().length === 0 ||
    value.length > maxLength
  ) {
    throw new TypeError(
      `${name} must be a non-empty string up to ${maxLength} characters.`,
    );
  }
  return value.trim();
}

function candidateInput(value: unknown): CandidateProfileCreate {
  if (typeof value !== "object" || value === null || !("contact" in value)) {
    throw new TypeError("Candidate profile input is invalid.");
  }
  const contact = value.contact;
  if (typeof contact !== "object" || contact === null) {
    throw new TypeError("Candidate contact input is invalid.");
  }
  return {
    display_name: requiredText(
      Reflect.get(value, "display_name"),
      "Display name",
      200,
    ),
    contact: {
      full_name: requiredText(
        Reflect.get(contact, "full_name"),
        "Full name",
        200,
      ),
      email: requiredText(Reflect.get(contact, "email"), "Email", 320),
      phone: null,
      address: null,
    },
  };
}

function mockWorkflowInput(value: unknown): MockWorkflowCreate {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Mock workflow input is invalid.");
  }
  return {
    profile_id: requiredText(
      Reflect.get(value, "profile_id"),
      "Profile id",
      100,
    ),
    employer: requiredText(Reflect.get(value, "employer"), "Employer", 200),
    title: requiredText(Reflect.get(value, "title"), "Title", 200),
  };
}

function referencePortalInput(value: unknown): ReferencePortalRunCreate {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Reference portal input is invalid.");
  }
  const portalOrigin = requiredText(
    Reflect.get(value, "portal_origin"),
    "Portal origin",
    2_000,
  );
  const parsed = new URL(portalOrigin);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new TypeError("Portal origin must use HTTP or HTTPS.");
  }
  return {
    profile_id: requiredText(
      Reflect.get(value, "profile_id"),
      "Profile id",
      100,
    ),
    portal_origin: parsed.origin,
    query: requiredText(Reflect.get(value, "query"), "Job query", 200),
    minimum_fit_score: 0.5,
  };
}

export function registerWorkbenchIpc(supervisor: BackendSupervisor): void {
  ipcMain.handle("workbench:get-status", () => supervisor.status);
  ipcMain.handle("workbench:list-workflows", () =>
    supervisor.client.listWorkflows(),
  );
  ipcMain.handle(
    "workbench:list-browser-sessions",
    (_event, value: unknown) => {
      if (value === undefined || value === null) {
        return supervisor.client.listBrowserSessions();
      }
      return supervisor.client.listBrowserSessions(
        requiredText(value, "Workflow id", 100),
      );
    },
  );
  ipcMain.handle("knowledge:get", (_event, value: unknown) =>
    supervisor.client.getCandidateKnowledge(
      requiredText(value, "Profile id", 100),
    ),
  );
  ipcMain.handle("knowledge:import-resume", async (_event, value: unknown) => {
    const profileId = requiredText(value, "Profile id", 100);
    const selection = await dialog.showOpenDialog({
      title: "Import candidate resume",
      properties: ["openFile"],
      filters: [
        {
          name: "Candidate documents",
          extensions: ["pdf", "docx", "rtf", "txt", "md"],
        },
      ],
    });
    const filePath = selection.filePaths[0];
    if (selection.canceled || !filePath) return null;
    return supervisor.client.importResume(profileId, filePath);
  });
  ipcMain.handle(
    "knowledge:review-claim",
    (_event, claimIdValue: unknown, approvedValue: unknown) => {
      const claimId = requiredText(claimIdValue, "Claim id", 100);
      if (typeof approvedValue !== "boolean") {
        throw new TypeError("Claim approval must be a boolean.");
      }
      return supervisor.client.reviewCandidateClaim(claimId, approvedValue);
    },
  );
  ipcMain.handle("workbench:create-candidate", (_event, value: unknown) =>
    supervisor.client.createCandidate(candidateInput(value)),
  );
  ipcMain.handle("workbench:start-mock", (_event, value: unknown) =>
    supervisor.client.startMockWorkflow(mockWorkflowInput(value)),
  );
  ipcMain.handle("portals:list-runs", () => supervisor.client.listPortalRuns());
  ipcMain.handle("portals:prepare-reference", (_event, value: unknown) =>
    supervisor.client.prepareReferencePortal(referencePortalInput(value)),
  );
  ipcMain.handle(
    "portals:confirm-reference",
    (_event, runIdValue: unknown, fingerprintValue: unknown) =>
      supervisor.client.confirmReferencePortal(
        requiredText(runIdValue, "Portal run id", 100),
        requiredText(fingerprintValue, "Review fingerprint", 200),
      ),
  );
  ipcMain.handle(
    "workbench:control",
    (_event, workflowIdValue: unknown, actionValue: unknown) => {
      const workflowId = requiredText(workflowIdValue, "Workflow id", 100);
      if (
        typeof actionValue !== "string" ||
        !actions.has(actionValue as WorkflowControlAction)
      ) {
        throw new TypeError("Workflow control action is invalid.");
      }
      return supervisor.client.controlWorkflow(
        workflowId,
        actionValue as WorkflowControlAction,
      );
    },
  );
}
