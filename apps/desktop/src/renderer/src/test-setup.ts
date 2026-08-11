import "@testing-library/jest-dom/vitest";

import type { DesktopBridge } from "@job-apply-pro/contracts";

const bridge: DesktopBridge = {
  platform: "win32",
  versions: { electron: "test", chrome: "test", node: "test" },
  workbench: {
    getStatus: async () => ({
      state: "ready",
      message: "Encrypted local backend connected.",
      checked_at: new Date(0).toISOString(),
    }),
    listWorkflows: async () => [],
    listBrowserSessions: async () => [],
    getCandidateKnowledge: async (profileId) => ({
      profile_id: profileId,
      documents: [],
      claims: [],
      answers: [],
    }),
    selectAndImportResume: async () => null,
    reviewCandidateClaim: async () => {
      throw new Error("Not implemented in this test.");
    },
    previewTailoredDocument: async () => {
      throw new Error("Not implemented in this test.");
    },
    generateTailoredDocument: async () => null,
    createCandidate: async () => {
      throw new Error("Not implemented in this test.");
    },
    startMockWorkflow: async () => {
      throw new Error("Not implemented in this test.");
    },
    controlWorkflow: async () => {
      throw new Error("Not implemented in this test.");
    },
    listPortalRuns: async () => [],
    listPortalCatalog: async () => [],
    prepareReferencePortal: async () => {
      throw new Error("Not implemented in this test.");
    },
    confirmReferencePortal: async () => {
      throw new Error("Not implemented in this test.");
    },
    listSupervisedPortalRuns: async () => [],
    startSupervisedPortal: async () => {
      throw new Error("Not implemented in this test.");
    },
    captureSupervisedPortal: async () => {
      throw new Error("Not implemented in this test.");
    },
    submitSupervisedPortal: async () => null,
    stopSupervisedPortal: async () => {
      throw new Error("Not implemented in this test.");
    },
    listChallengeSessions: async () => [],
    detectChallenge: async () => {
      throw new Error("Not implemented in this test.");
    },
    getChallengeSuggestions: async () => [],
    getChallengeModelRoutes: async () => [],
    refreshChallenge: async () => {
      throw new Error("Not implemented in this test.");
    },
    answerChallenge: async () => {
      throw new Error("Not implemented in this test.");
    },
    completeChallenge: async () => {
      throw new Error("Not implemented in this test.");
    },
    completeChallengeIntervention: async () => {
      throw new Error("Not implemented in this test.");
    },
    listIntegrationHealth: async () => [
      {
        provider: "GMAIL",
        status: "NOT_CONFIGURED",
        message: "OAuth is not configured",
        read_enabled: false,
        write_enabled: false,
        granted_scopes: [],
      },
    ],
    getProviderConfigurationStatus: async () => ({
      source: "NOT_CONFIGURED",
      providers: [],
      automatic_categories: [],
      updated_at: null,
    }),
    selectAndImportProviderConfiguration: async () => null,
    clearProviderConfiguration: async () => null,
    startProviderAuthorization: async () => {
      throw new Error("OAuth client is not configured in this test.");
    },
    revokeProviderAuthorization: async (provider) => ({
      provider,
      status: "AUTHORIZATION_REQUIRED",
      granted_scopes: [],
    }),
    syncProviderMessages: async (provider) => ({
      provider,
      fetched_count: 0,
      imported_count: 0,
      duplicate_count: 0,
      record_ids: [],
      sync_mode: "INITIAL",
      cursor_updated_at: new Date(0).toISOString(),
    }),
    listCommunicationRecords: async () => [],
    getDailyCommunicationSummary: async () => ({
      generated_at: new Date(0).toISOString(),
      analyzed_messages: 0,
      review_required: 0,
      scheduled_follow_ups: 0,
      due_follow_ups: 0,
      planned_mutations: 0,
      confirmed_mutations: 0,
    }),
    getDesktopNotificationStatus: async () => ({
      native_enabled: false,
      native_supported: true,
      poll_interval_seconds: 60,
      active_notifications: [],
      delivered_count: 0,
      last_checked_at: new Date(0).toISOString(),
      last_error: null,
    }),
    refreshDesktopNotifications: async () => ({
      native_enabled: false,
      native_supported: true,
      poll_interval_seconds: 60,
      active_notifications: [],
      delivered_count: 0,
      last_checked_at: new Date(0).toISOString(),
      last_error: null,
    }),
    setNativeNotificationsEnabled: async (enabled) => ({
      native_enabled: enabled,
      native_supported: true,
      poll_interval_seconds: 60,
      active_notifications: [],
      delivered_count: 0,
      last_checked_at: new Date(0).toISOString(),
      last_error: null,
    }),
    getOperationsDashboard: async () => ({
      generated_at: new Date(0).toISOString(),
      applications: {
        jobs_discovered: 0,
        applications_total: 0,
        submission_attempted: 0,
        submission_confirmed: 0,
        tracking_active: 0,
        failed: 0,
        duplicated: 0,
        interviews_received: 0,
        offers_received: 0,
        recruiter_messages: 0,
      },
      models: {
        invocations: 0,
        successful: 0,
        failed: 0,
        input_tokens: 0,
        output_tokens: 0,
        cost_micros: 0,
        average_latency_ms: 0,
        by_provider: {},
      },
      portals: [],
      application_report: [],
      interview_report: [],
      backup_count: 0,
      latest_backup: null,
      license: {
        status: "DEVELOPMENT",
        message: "Development entitlement",
        recovery_allowed: true,
        payment_enabled: false,
      },
    }),
    listBackups: async () => [],
    listBackupSchedules: async () => [],
    createBackup: async () => {
      throw new Error("Not implemented in this test.");
    },
    createBackupSchedule: async () => {
      throw new Error("Not implemented in this test.");
    },
    verifyBackup: async () => ({
      backup_id: "backup-test",
      valid: true,
      reasons: [],
      verified_entries: 0,
      verified_at: new Date(0).toISOString(),
    }),
    stageRestore: async () => {
      throw new Error("Not implemented in this test.");
    },
    applyRestore: async () => false,
    listHelpTopics: async () => [],
    exportSupportDiagnostics: async () => null,
    getUpdateStatus: async () => ({
      state: "DISABLED",
      current_version: "0.20.0-alpha.1",
      message: "Updates are disabled for development builds.",
      checked_at: new Date(0).toISOString(),
    }),
    checkForUpdates: async () => ({
      state: "DISABLED",
      current_version: "0.20.0-alpha.1",
      message: "Updates are disabled for development builds.",
      checked_at: new Date(0).toISOString(),
    }),
    downloadUpdate: async () => ({
      state: "DISABLED",
      current_version: "0.20.0-alpha.1",
      message: "Updates are disabled for development builds.",
      checked_at: new Date(0).toISOString(),
    }),
    installUpdate: async () => undefined,
    onUpdateStatus: (listener) => {
      listener({
        state: "DISABLED",
        current_version: "0.20.0-alpha.1",
        message: "Updates are disabled for development builds.",
        checked_at: new Date(0).toISOString(),
      });
      return () => undefined;
    },
    onDesktopNotificationStatus: () => () => undefined,
    onDesktopNotificationActivated: () => () => undefined,
    onStatus: () => () => undefined,
  },
};

Object.defineProperty(window, "jobApplyPro", {
  value: bridge,
  configurable: true,
});
