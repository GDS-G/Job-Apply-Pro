import { ipcMain } from "electron";

import type {
  CandidateProfileCreate,
  MockWorkflowCreate,
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

export function registerWorkbenchIpc(supervisor: BackendSupervisor): void {
  ipcMain.handle("workbench:get-status", () => supervisor.status);
  ipcMain.handle("workbench:list-workflows", () =>
    supervisor.client.listWorkflows(),
  );
  ipcMain.handle("workbench:create-candidate", (_event, value: unknown) =>
    supervisor.client.createCandidate(candidateInput(value)),
  );
  ipcMain.handle("workbench:start-mock", (_event, value: unknown) =>
    supervisor.client.startMockWorkflow(mockWorkflowInput(value)),
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
