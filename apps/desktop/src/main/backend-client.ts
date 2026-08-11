import { readFile } from "node:fs/promises";
import { basename } from "node:path";

import type {
  BackupManifest,
  BackupSchedule,
  BackupVerification,
  BrowserSessionSnapshot,
  CandidateClaim,
  CandidateDocumentImportResult,
  CandidateKnowledgeSnapshot,
  CandidateProfile,
  CandidateProfileCreate,
  ChallengeAnswerCommand,
  ChallengeAnswerSuggestion,
  ChallengeModelRoute,
  ChallengeSessionCreate,
  ChallengeSessionSnapshot,
  CommunicationRecord,
  DailyCommunicationSummary,
  IntegrationHealth,
  IntegrationProvider,
  HelpTopic,
  MockWorkflowCreate,
  OperationsDashboard,
  OAuthAuthorizationRequest,
  OAuthAuthorizationState,
  ProviderConfigurationStatus,
  ProviderMessageSyncResult,
  PortalRunSnapshot,
  PortalAdapterDefinition,
  ReferencePortalRunCreate,
  RestorePlan,
  SupervisedPortalRunCreate,
  SupervisedPortalRunSnapshot,
  SupportDiagnostics,
  TailoredDocumentPreview,
  TailoredDocumentRequest,
  TailoredDocumentResult,
  WorkflowControlAction,
  WorkflowRunSnapshot,
} from "@job-apply-pro/contracts";

export class BackendApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "BackendApiError";
  }
}

export class BackendClient {
  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
  ) {}

  async runtimeStatus(): Promise<void> {
    await this.request("/runtime/status");
  }

  listWorkflows(): Promise<WorkflowRunSnapshot[]> {
    return this.request("/workbench/workflows");
  }

  listBrowserSessions(workflowId?: string): Promise<BrowserSessionSnapshot[]> {
    const query = workflowId
      ? `?workflow_id=${encodeURIComponent(workflowId)}`
      : "";
    return this.request(`/browser/sessions${query}`);
  }

  getCandidateKnowledge(
    profileId: string,
  ): Promise<CandidateKnowledgeSnapshot> {
    return this.request(
      `/knowledge/profiles/${encodeURIComponent(profileId)}/snapshot`,
    );
  }

  async importResume(
    profileId: string,
    filePath: string,
  ): Promise<CandidateDocumentImportResult> {
    const data = await readFile(filePath);
    const form = new FormData();
    form.append("file", new Blob([data]), basename(filePath));
    form.append("kind", "RESUME");
    form.append("display_name", basename(filePath));
    form.append("variant_label", "General");
    form.append("is_primary", "false");
    const imported = await this.request<{
      extraction: CandidateDocumentImportResult["extraction"];
    }>(`/knowledge/profiles/${encodeURIComponent(profileId)}/documents`, {
      method: "POST",
      body: form,
    });
    return {
      snapshot: await this.getCandidateKnowledge(profileId),
      extraction: imported.extraction,
    };
  }

  reviewCandidateClaim(
    claimId: string,
    approved: boolean,
  ): Promise<CandidateClaim> {
    return this.request(
      `/knowledge/claims/${encodeURIComponent(claimId)}/review`,
      {
        method: "POST",
        body: JSON.stringify({
          approved,
          lock: approved,
          permitted_use: approved ? "APPLICATIONS" : "PROFILE_ONLY",
        }),
      },
    );
  }

  previewTailoredDocument(
    input: TailoredDocumentRequest,
  ): Promise<TailoredDocumentPreview> {
    return this.request("/knowledge/documents/tailored/preview", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  generateTailoredDocument(
    input: TailoredDocumentRequest,
    reviewFingerprint: string,
  ): Promise<TailoredDocumentResult> {
    return this.request("/knowledge/documents/tailored/generate", {
      method: "POST",
      body: JSON.stringify({
        ...input,
        review_fingerprint: reviewFingerprint,
        confirmation_phrase: "APPROVE TAILORED DOCUMENT",
      }),
    });
  }

  async getDocumentContent(versionId: string): Promise<Uint8Array> {
    const response = await fetch(
      `${this.baseUrl}/knowledge/document-versions/${encodeURIComponent(versionId)}/content`,
      {
        headers: { "X-Job-Apply-Pro-Token": this.token },
        signal: AbortSignal.timeout(10_000),
      },
    );
    if (!response.ok) {
      const payload: unknown = await response.json().catch(() => null);
      const detail =
        typeof payload === "object" && payload !== null && "detail" in payload
          ? String(payload.detail)
          : `Local backend request failed with HTTP ${response.status}`;
      throw new BackendApiError(detail, response.status);
    }
    return new Uint8Array(await response.arrayBuffer());
  }

  createCandidate(input: CandidateProfileCreate): Promise<CandidateProfile> {
    return this.request("/candidates", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  startMockWorkflow(input: MockWorkflowCreate): Promise<WorkflowRunSnapshot> {
    return this.request("/workbench/mock-workflows", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  controlWorkflow(
    workflowId: string,
    action: WorkflowControlAction,
  ): Promise<WorkflowRunSnapshot> {
    return this.request(
      `/workbench/workflows/${encodeURIComponent(workflowId)}/controls`,
      {
        method: "POST",
        body: JSON.stringify({ action }),
      },
    );
  }

  listPortalRuns(): Promise<PortalRunSnapshot[]> {
    return this.request("/portals/runs");
  }

  listPortalCatalog(): Promise<PortalAdapterDefinition[]> {
    return this.request("/portals/catalog");
  }

  prepareReferencePortal(
    input: ReferencePortalRunCreate,
  ): Promise<PortalRunSnapshot> {
    return this.request(
      "/portals/reference/runs",
      {
        method: "POST",
        body: JSON.stringify(input),
      },
      120_000,
    );
  }

  confirmReferencePortal(
    runId: string,
    reviewFingerprint: string,
  ): Promise<PortalRunSnapshot> {
    return this.request(
      `/portals/runs/${encodeURIComponent(runId)}/confirm`,
      {
        method: "POST",
        body: JSON.stringify({
          review_fingerprint: reviewFingerprint,
          confirmation_phrase: "SUBMIT REFERENCE APPLICATION",
        }),
      },
      120_000,
    );
  }

  listSupervisedPortalRuns(): Promise<SupervisedPortalRunSnapshot[]> {
    return this.request("/portals/supervised/runs");
  }

  startSupervisedPortal(
    input: SupervisedPortalRunCreate,
  ): Promise<SupervisedPortalRunSnapshot> {
    return this.request(
      "/portals/supervised/runs",
      { method: "POST", body: JSON.stringify(input) },
      120_000,
    );
  }

  captureSupervisedPortal(
    runId: string,
    priorPageFingerprint: string,
  ): Promise<SupervisedPortalRunSnapshot> {
    return this.request(
      `/portals/supervised/runs/${encodeURIComponent(runId)}/capture`,
      {
        method: "POST",
        body: JSON.stringify({
          prior_page_fingerprint: priorPageFingerprint,
        }),
      },
      120_000,
    );
  }

  submitSupervisedPortal(
    runId: string,
    reviewFingerprint: string,
  ): Promise<SupervisedPortalRunSnapshot> {
    return this.request(
      `/portals/supervised/runs/${encodeURIComponent(runId)}/submit`,
      {
        method: "POST",
        body: JSON.stringify({
          review_fingerprint: reviewFingerprint,
          confirmation_phrase: "SUBMIT APPLICATION",
        }),
      },
      120_000,
    );
  }

  stopSupervisedPortal(runId: string): Promise<SupervisedPortalRunSnapshot> {
    return this.request(
      `/portals/supervised/runs/${encodeURIComponent(runId)}/stop`,
      { method: "POST" },
      120_000,
    );
  }

  listChallengeSessions(
    workflowId?: string,
  ): Promise<ChallengeSessionSnapshot[]> {
    const query = workflowId
      ? `?workflow_id=${encodeURIComponent(workflowId)}`
      : "";
    return this.request(`/challenges/sessions${query}`);
  }

  detectChallenge(
    input: ChallengeSessionCreate,
  ): Promise<ChallengeSessionSnapshot> {
    return this.request(
      "/challenges/detect",
      { method: "POST", body: JSON.stringify(input) },
      120_000,
    );
  }

  getChallengeSuggestions(
    sessionId: string,
  ): Promise<ChallengeAnswerSuggestion[]> {
    return this.request(
      `/challenges/sessions/${encodeURIComponent(sessionId)}/suggestions`,
    );
  }

  getChallengeModelRoutes(sessionId: string): Promise<ChallengeModelRoute[]> {
    return this.request(
      `/challenges/sessions/${encodeURIComponent(sessionId)}/model-routes`,
    );
  }

  refreshChallenge(sessionId: string): Promise<ChallengeSessionSnapshot> {
    return this.request(
      `/challenges/sessions/${encodeURIComponent(sessionId)}/refresh`,
      { method: "POST" },
      120_000,
    );
  }

  answerChallenge(
    sessionId: string,
    input: ChallengeAnswerCommand,
  ): Promise<ChallengeSessionSnapshot> {
    return this.request(
      `/challenges/sessions/${encodeURIComponent(sessionId)}/answers`,
      { method: "POST", body: JSON.stringify(input) },
      120_000,
    );
  }

  completeChallenge(
    sessionId: string,
    reviewFingerprint: string,
  ): Promise<ChallengeSessionSnapshot> {
    return this.request(
      `/challenges/sessions/${encodeURIComponent(sessionId)}/complete`,
      {
        method: "POST",
        body: JSON.stringify({
          review_fingerprint: reviewFingerprint,
          confirmation_phrase: "COMPLETE CHALLENGE",
        }),
      },
      120_000,
    );
  }

  completeChallengeIntervention(
    sessionId: string,
    priorFingerprint: string,
  ): Promise<ChallengeSessionSnapshot> {
    return this.request(
      `/challenges/sessions/${encodeURIComponent(sessionId)}/intervention-complete`,
      {
        method: "POST",
        body: JSON.stringify({ prior_fingerprint: priorFingerprint }),
      },
      120_000,
    );
  }

  listIntegrationHealth(): Promise<IntegrationHealth[]> {
    return this.request("/communications/integrations");
  }

  getProviderConfigurationStatus(): Promise<ProviderConfigurationStatus> {
    return this.request("/communications/configuration");
  }

  validateProviderConfiguration(
    configurationJson: string,
  ): Promise<ProviderConfigurationStatus> {
    return this.request("/communications/configuration/validate", {
      method: "POST",
      body: JSON.stringify({ configuration_json: configurationJson }),
    });
  }

  importProviderConfiguration(
    configurationJson: string,
  ): Promise<ProviderConfigurationStatus> {
    return this.request("/communications/configuration/import", {
      method: "POST",
      body: JSON.stringify({ configuration_json: configurationJson }),
    });
  }

  clearProviderConfiguration(): Promise<ProviderConfigurationStatus> {
    return this.request("/communications/configuration", { method: "DELETE" });
  }

  startProviderAuthorization(
    provider: IntegrationProvider,
  ): Promise<OAuthAuthorizationRequest> {
    return this.request(
      `/communications/oauth/${encodeURIComponent(provider)}/start`,
      { method: "POST" },
    );
  }

  revokeProviderAuthorization(
    provider: IntegrationProvider,
  ): Promise<OAuthAuthorizationState> {
    return this.request(
      `/communications/oauth/${encodeURIComponent(provider)}/revoke`,
      { method: "POST" },
    );
  }

  syncProviderMessages(
    provider: IntegrationProvider,
  ): Promise<ProviderMessageSyncResult> {
    return this.request(
      `/communications/providers/${encodeURIComponent(provider)}/messages/sync`,
      { method: "POST" },
      120_000,
    );
  }

  listCommunicationRecords(): Promise<CommunicationRecord[]> {
    return this.request("/communications/records");
  }

  getDailyCommunicationSummary(): Promise<DailyCommunicationSummary> {
    return this.request("/communications/daily-summary");
  }

  getOperationsDashboard(): Promise<OperationsDashboard> {
    return this.request("/operations/dashboard");
  }

  listBackups(): Promise<BackupManifest[]> {
    return this.request("/operations/backups");
  }

  listBackupSchedules(): Promise<BackupSchedule[]> {
    return this.request("/operations/backup-schedules");
  }

  createBackup(label: string): Promise<BackupManifest> {
    return this.request("/operations/backups", {
      method: "POST",
      body: JSON.stringify({
        label,
        categories: ["DATABASE", "DOCUMENTS"],
      }),
    });
  }

  createBackupSchedule(
    label: string,
    intervalHours: number,
  ): Promise<BackupSchedule> {
    return this.request("/operations/backup-schedules", {
      method: "POST",
      body: JSON.stringify({
        label,
        categories: ["DATABASE", "DOCUMENTS"],
        interval_hours: intervalHours,
        enabled: true,
      }),
    });
  }

  runDueBackupSchedules(): Promise<BackupManifest[]> {
    return this.request(
      "/operations/backup-schedules/run-due",
      {
        method: "POST",
      },
      120_000,
    );
  }

  verifyBackup(backupId: string): Promise<BackupVerification> {
    return this.request(
      `/operations/backups/${encodeURIComponent(backupId)}/verify`,
      { method: "POST" },
    );
  }

  stageRestore(backupId: string): Promise<RestorePlan> {
    return this.request(
      `/operations/backups/${encodeURIComponent(backupId)}/restore-plans`,
      {
        method: "POST",
        body: JSON.stringify({ categories: ["DATABASE", "DOCUMENTS"] }),
      },
      120_000,
    );
  }

  listHelpTopics(): Promise<HelpTopic[]> {
    return this.request("/operations/help");
  }

  getSupportDiagnostics(): Promise<SupportDiagnostics> {
    return this.request("/operations/diagnostics", {}, 30_000);
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    timeoutMs = 10_000,
  ): Promise<T> {
    const isForm = init.body instanceof FormData;
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        "X-Job-Apply-Pro-Token": this.token,
        ...init.headers,
      },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) {
      const payload: unknown = await response.json().catch(() => null);
      const detail =
        typeof payload === "object" && payload !== null && "detail" in payload
          ? String(payload.detail)
          : `Local backend request failed with HTTP ${response.status}`;
      throw new BackendApiError(detail, response.status);
    }
    return (await response.json()) as T;
  }
}
