import { readFile } from "node:fs/promises";
import { basename } from "node:path";

import type {
  BrowserSessionSnapshot,
  CandidateClaim,
  CandidateKnowledgeSnapshot,
  CandidateProfile,
  CandidateProfileCreate,
  ChallengeAnswerCommand,
  ChallengeAnswerSuggestion,
  ChallengeModelRoute,
  ChallengeSessionCreate,
  ChallengeSessionSnapshot,
  MockWorkflowCreate,
  PortalRunSnapshot,
  PortalAdapterDefinition,
  ReferencePortalRunCreate,
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
  ): Promise<CandidateKnowledgeSnapshot> {
    const data = await readFile(filePath);
    const form = new FormData();
    form.append("file", new Blob([data]), basename(filePath));
    form.append("kind", "RESUME");
    form.append("display_name", basename(filePath));
    form.append("variant_label", "General");
    form.append("is_primary", "false");
    await this.request(
      `/knowledge/profiles/${encodeURIComponent(profileId)}/documents`,
      { method: "POST", body: form },
    );
    return this.getCandidateKnowledge(profileId);
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
