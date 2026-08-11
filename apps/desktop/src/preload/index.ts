import { contextBridge, ipcRenderer } from "electron";

import type {
  BackendRuntimeStatus,
  CandidateProfileCreate,
  MockWorkflowCreate,
  ReferencePortalRunCreate,
  WorkflowControlAction,
} from "@job-apply-pro/contracts";

contextBridge.exposeInMainWorld("jobApplyPro", {
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },
  workbench: {
    getStatus: () => ipcRenderer.invoke("workbench:get-status"),
    listWorkflows: () => ipcRenderer.invoke("workbench:list-workflows"),
    listBrowserSessions: (workflowId?: string) =>
      ipcRenderer.invoke("workbench:list-browser-sessions", workflowId),
    getCandidateKnowledge: (profileId: string) =>
      ipcRenderer.invoke("knowledge:get", profileId),
    selectAndImportResume: (profileId: string) =>
      ipcRenderer.invoke("knowledge:import-resume", profileId),
    reviewCandidateClaim: (claimId: string, approved: boolean) =>
      ipcRenderer.invoke("knowledge:review-claim", claimId, approved),
    createCandidate: (input: CandidateProfileCreate) =>
      ipcRenderer.invoke("workbench:create-candidate", input),
    startMockWorkflow: (input: MockWorkflowCreate) =>
      ipcRenderer.invoke("workbench:start-mock", input),
    controlWorkflow: (workflowId: string, action: WorkflowControlAction) =>
      ipcRenderer.invoke("workbench:control", workflowId, action),
    listPortalRuns: () => ipcRenderer.invoke("portals:list-runs"),
    prepareReferencePortal: (input: ReferencePortalRunCreate) =>
      ipcRenderer.invoke("portals:prepare-reference", input),
    confirmReferencePortal: (runId: string, reviewFingerprint: string) =>
      ipcRenderer.invoke("portals:confirm-reference", runId, reviewFingerprint),
    onStatus: (listener: (status: BackendRuntimeStatus) => void) => {
      const handler = (
        _event: Electron.IpcRendererEvent,
        status: BackendRuntimeStatus,
      ) => listener(status);
      ipcRenderer.on("workbench:status", handler);
      return () => ipcRenderer.removeListener("workbench:status", handler);
    },
  },
});
