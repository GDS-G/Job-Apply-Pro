export const buildInfo = {
  name: "Foundation",
  version: "0.1.0-alpha.1",
  channel: "alpha",
} as const;

export const workflowStates = [
  "DISCOVERED",
  "DEDUPLICATED",
  "SCORED",
  "ELIGIBILITY_CHECKED",
  "DOCUMENTS_SELECTED",
  "APPLICATION_OPENED",
  "FORM_MAPPED",
  "ANSWERS_VALIDATED",
  "ASSESSMENT_PENDING",
  "ASSESSMENT_IN_PROGRESS",
  "ASSESSMENT_COMPLETED",
  "READY_TO_SUBMIT",
  "SUBMISSION_ATTEMPTED",
  "SUBMISSION_CONFIRMED",
  "TRACKING_ACTIVE",
  "CLOSED",
  "LOGIN_REQUIRED",
  "MFA_REQUIRED",
  "CAPTCHA_REQUIRED",
  "UNKNOWN_QUESTION",
  "SENSITIVE_FIELD",
  "ASSESSMENT_REQUIRED",
  "SITE_CHANGED",
  "SESSION_EXPIRED",
  "POLICY_REVIEW",
  "USER_TAKEOVER",
  "SUBMISSION_UNCERTAIN",
  "FAILED_RETRYABLE",
  "FAILED_TERMINAL",
] as const;

export type WorkflowState = (typeof workflowStates)[number];
export type VerificationResult =
  "NOT_REQUIRED" | "PASSED" | "FAILED" | "UNCERTAIN";

export interface HealthResponse {
  status: "ok" | "degraded";
  service: "job-apply-pro-backend";
  version: string;
  build: string;
  environment: string;
}

export interface DashboardMetric {
  label: string;
  value: number;
  delta: string;
  tone: "indigo" | "emerald" | "amber" | "slate";
}

export interface QueueItem {
  id: string;
  employer: string;
  role: string;
  state: WorkflowState;
  progress: number;
  mode: "Supervised" | "Autonomous";
}

export interface ActivityItem {
  id: string;
  title: string;
  detail: string;
  occurred_at: string;
  severity: "info" | "success" | "warning";
}

export interface DashboardSummary {
  metrics: DashboardMetric[];
  queue: QueueItem[];
  activity: ActivityItem[];
  automation_enabled: boolean;
}

export interface DesktopBridge {
  platform:
    | "aix"
    | "android"
    | "darwin"
    | "freebsd"
    | "haiku"
    | "linux"
    | "openbsd"
    | "sunos"
    | "win32";
  versions: {
    electron: string;
    chrome: string;
    node: string;
  };
  apiBaseUrl: string;
}
