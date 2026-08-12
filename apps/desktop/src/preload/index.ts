import { contextBridge, ipcRenderer } from "electron";

import type {
  AnswerLibraryInput,
  BackendRuntimeStatus,
  CandidateDocumentImportInput,
  DesktopNotificationDestination,
  DesktopNotificationStatus,
  DesktopUpdateStatus,
  DocumentSelectionRequest,
  CandidateProfileCreate,
  ChallengeAnswerCommand,
  ChallengeSessionCreate,
  IntegrationProvider,
  MockWorkflowCreate,
  ReferencePortalRunCreate,
  SupervisedPortalRunCreate,
  TailoredDocumentRequest,
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
    selectAndImportResume: (
      profileId: string,
      input: CandidateDocumentImportInput,
    ) => ipcRenderer.invoke("knowledge:import-resume", profileId, input),
    previewDocumentSelection: (input: DocumentSelectionRequest) =>
      ipcRenderer.invoke("knowledge:preview-selection", input),
    approveDocumentSelection: (
      input: DocumentSelectionRequest,
      documentVersionId: string,
      reviewFingerprint: string,
    ) =>
      ipcRenderer.invoke(
        "knowledge:approve-selection",
        input,
        documentVersionId,
        reviewFingerprint,
      ),
    reviewCandidateClaim: (claimId: string, approved: boolean) =>
      ipcRenderer.invoke("knowledge:review-claim", claimId, approved),
    createAnswer: (profileId: string, input: AnswerLibraryInput) =>
      ipcRenderer.invoke("knowledge:create-answer", profileId, input),
    updateAnswer: (
      answerId: string,
      expectedRevision: number,
      input: AnswerLibraryInput,
    ) =>
      ipcRenderer.invoke(
        "knowledge:update-answer",
        answerId,
        expectedRevision,
        input,
      ),
    listAnswerRevisions: (answerId: string) =>
      ipcRenderer.invoke("knowledge:list-answer-revisions", answerId),
    previewTailoredDocument: (input: TailoredDocumentRequest) =>
      ipcRenderer.invoke("knowledge:preview-tailored", input),
    generateTailoredDocument: (
      input: TailoredDocumentRequest,
      reviewFingerprint: string,
    ) =>
      ipcRenderer.invoke(
        "knowledge:generate-tailored",
        input,
        reviewFingerprint,
      ),
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
    listSupervisedPortalRuns: () =>
      ipcRenderer.invoke("portals:list-supervised"),
    startSupervisedPortal: (input: SupervisedPortalRunCreate) =>
      ipcRenderer.invoke("portals:start-supervised", input),
    captureSupervisedPortal: (runId: string, priorPageFingerprint: string) =>
      ipcRenderer.invoke(
        "portals:capture-supervised",
        runId,
        priorPageFingerprint,
      ),
    submitSupervisedPortal: (runId: string, reviewFingerprint: string) =>
      ipcRenderer.invoke("portals:submit-supervised", runId, reviewFingerprint),
    stopSupervisedPortal: (runId: string) =>
      ipcRenderer.invoke("portals:stop-supervised", runId),
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
    getProviderConfigurationStatus: () =>
      ipcRenderer.invoke("communications:configuration"),
    selectAndImportProviderConfiguration: () =>
      ipcRenderer.invoke("communications:configuration-import"),
    clearProviderConfiguration: () =>
      ipcRenderer.invoke("communications:configuration-clear"),
    startProviderAuthorization: (provider: IntegrationProvider) =>
      ipcRenderer.invoke("communications:oauth-start", provider),
    revokeProviderAuthorization: (provider: IntegrationProvider) =>
      ipcRenderer.invoke("communications:oauth-revoke", provider),
    syncProviderMessages: (provider: IntegrationProvider) =>
      ipcRenderer.invoke("communications:messages-sync", provider),
    syncProviderCalendar: (provider: IntegrationProvider) =>
      ipcRenderer.invoke("communications:calendar-sync", provider),
    listSyncedCalendarEvents: () =>
      ipcRenderer.invoke("communications:calendar-events"),
    listCommunicationRecords: () =>
      ipcRenderer.invoke("communications:records"),
    getDailyCommunicationSummary: () =>
      ipcRenderer.invoke("communications:daily-summary"),
    getDesktopNotificationStatus: () =>
      ipcRenderer.invoke("notifications:status"),
    refreshDesktopNotifications: () =>
      ipcRenderer.invoke("notifications:refresh"),
    setNativeNotificationsEnabled: (enabled: boolean) =>
      ipcRenderer.invoke("notifications:set-native-enabled", enabled),
    getOperationsDashboard: () => ipcRenderer.invoke("operations:dashboard"),
    listBackups: () => ipcRenderer.invoke("operations:backups"),
    listBackupSchedules: () =>
      ipcRenderer.invoke("operations:backup-schedules"),
    createBackup: (label: string) =>
      ipcRenderer.invoke("operations:create-backup", label),
    createBackupSchedule: (label: string, intervalHours: number) =>
      ipcRenderer.invoke(
        "operations:create-backup-schedule",
        label,
        intervalHours,
      ),
    verifyBackup: (backupId: string) =>
      ipcRenderer.invoke("operations:verify-backup", backupId),
    stageRestore: (backupId: string) =>
      ipcRenderer.invoke("operations:stage-restore", backupId),
    applyRestore: (planId: string, fingerprint: string) =>
      ipcRenderer.invoke("operations:apply-restore", planId, fingerprint),
    listHelpTopics: () => ipcRenderer.invoke("operations:help"),
    exportSupportDiagnostics: () =>
      ipcRenderer.invoke("operations:export-diagnostics"),
    getUpdateStatus: () => ipcRenderer.invoke("updates:status"),
    checkForUpdates: () => ipcRenderer.invoke("updates:check"),
    downloadUpdate: () => ipcRenderer.invoke("updates:download"),
    installUpdate: () => ipcRenderer.invoke("updates:install"),
    onUpdateStatus: (listener: (status: DesktopUpdateStatus) => void) => {
      const handler = (
        _event: Electron.IpcRendererEvent,
        status: DesktopUpdateStatus,
      ) => listener(status);
      ipcRenderer.on("updates:status", handler);
      return () => ipcRenderer.removeListener("updates:status", handler);
    },
    onDesktopNotificationStatus: (
      listener: (status: DesktopNotificationStatus) => void,
    ) => {
      const handler = (
        _event: Electron.IpcRendererEvent,
        status: DesktopNotificationStatus,
      ) => listener(status);
      ipcRenderer.on("notifications:status", handler);
      return () => ipcRenderer.removeListener("notifications:status", handler);
    },
    onDesktopNotificationActivated: (
      listener: (destination: DesktopNotificationDestination) => void,
    ) => {
      const handler = (
        _event: Electron.IpcRendererEvent,
        destination: DesktopNotificationDestination,
      ) => listener(destination);
      ipcRenderer.on("notifications:activated", handler);
      return () =>
        ipcRenderer.removeListener("notifications:activated", handler);
    },
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
