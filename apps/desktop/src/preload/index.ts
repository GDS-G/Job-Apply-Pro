import { contextBridge, ipcRenderer } from "electron";

import type {
  BackendRuntimeStatus,
  CandidateProfileCreate,
  MockWorkflowCreate,
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
    createCandidate: (input: CandidateProfileCreate) =>
      ipcRenderer.invoke("workbench:create-candidate", input),
    startMockWorkflow: (input: MockWorkflowCreate) =>
      ipcRenderer.invoke("workbench:start-mock", input),
    controlWorkflow: (workflowId: string, action: WorkflowControlAction) =>
      ipcRenderer.invoke("workbench:control", workflowId, action),
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
