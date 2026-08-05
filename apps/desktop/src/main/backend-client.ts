import type {
  CandidateProfile,
  CandidateProfileCreate,
  MockWorkflowCreate,
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

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-Job-Apply-Pro-Token": this.token,
        ...init.headers,
      },
      signal: AbortSignal.timeout(10_000),
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
