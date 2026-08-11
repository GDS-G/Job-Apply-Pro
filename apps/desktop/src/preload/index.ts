import { contextBridge, ipcRenderer } from "electron";

import type {
  BackendRuntimeStatus,
  CandidateProfileCreate,
  ChallengeAnswerCommand,
  ChallengeSessionCreate,
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
    listPortalCatalog: () => ipcRenderer.invoke("portals:list-catalog"),
    prepareReferencePortal: (input: ReferencePortalRunCreate) =>
      ipcRenderer.invoke("portals:prepare-reference", input),
    confirmReferencePortal: (runId: string, reviewFingerprint: string) =>
      ipcRenderer.invoke("portals:confirm-reference", runId, reviewFingerprint),
    listChallengeSessions: (workflowId?: string) =>
      ipcRenderer.invoke("challenges:list", workflowId),
    detectChallenge: (input: ChallengeSessionCreate) =>
      ipcRenderer.invoke("challenges:detect", input),
    getChallengeSuggestions: (sessionId: string) =>
      ipcRenderer.invoke("challenges:suggestions", sessionId),
    getChallengeModelRoutes: (sessionId: string) =>
      ipcRenderer.invoke("challenges:model-routes", sessionId),
    refreshChallenge: (sessionId: string) =>
      ipcRenderer.invoke("challenges:refresh", sessionId),
    answerChallenge: (sessionId: string, input: ChallengeAnswerCommand) =>
      ipcRenderer.invoke("challenges:answer", sessionId, input),
    completeChallenge: (sessionId: string, reviewFingerprint: string) =>
      ipcRenderer.invoke("challenges:complete", sessionId, reviewFingerprint),
    completeChallengeIntervention: (
      sessionId: string,
      priorFingerprint: string,
    ) =>
      ipcRenderer.invoke(
        "challenges:intervention-complete",
        sessionId,
        priorFingerprint,
      ),
    listIntegrationHealth: () =>
      ipcRenderer.invoke("communications:integrations"),
    listCommunicationRecords: () =>
      ipcRenderer.invoke("communications:records"),
    getDailyCommunicationSummary: () =>
      ipcRenderer.invoke("communications:daily-summary"),
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
