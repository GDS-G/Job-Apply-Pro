export const buildInfo = {
  name: "Portal Vertical Slice",
  version: "0.7.0-alpha.1",
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

export type CandidateStatus = "DRAFT" | "ACTIVE" | "ARCHIVED";

export interface ContactDetails {
  full_name: string;
  email: string;
  phone?: string | null;
  address?: string | null;
}

export interface CandidateProfile {
  id: string;
  display_name: string;
  contact: ContactDetails;
  status: CandidateStatus;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  source: string;
  external_id: string;
  employer: string;
  title: string;
  location?: string | null;
  source_url?: string | null;
  description_hash: string;
  discovered_at: string;
}

export interface Application {
  id: string;
  workflow_id: string;
  profile_id: string;
  job_id: string;
  state: WorkflowState;
  selected_document_version_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowCheckpoint {
  id: string;
  workflow_id: string;
  sequence: number;
  state: WorkflowState;
  page_fingerprint: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface WorkflowEvent {
  id: string;
  workflow_id: string;
  sequence: number;
  prior_state: WorkflowState;
  next_state: WorkflowState;
  actor: string;
  cause: string;
  verification: VerificationResult;
  retry_count: number;
  occurred_at: string;
}

export type BrowserEngine = "chromium" | "chrome" | "msedge";
export type BrowserSessionState =
  "STARTING" | "ACTIVE" | "USER_TAKEOVER" | "STOPPED" | "FAILED";

export interface BrowserTab {
  index: number;
  url: string;
  title: string;
  active: boolean;
}

export interface BrowserObservation {
  sequence: number;
  url: string;
  title: string;
  origin: string;
  page_type: string;
  page_fingerprint: string;
  tabs: BrowserTab[];
  accessibility_snapshot: string;
  visible_text: string;
  controls: Record<string, unknown>[];
  validation_errors: string[];
  modals: string[];
  console_errors: string[];
  network_failures: string[];
  upload_status: string[];
  download_status: string[];
  screenshot_path: string;
  trace_path?: string | null;
  previous_action?: string | null;
  observed_at: string;
}

export interface BrowserSessionSnapshot {
  id: string;
  workflow_id: string;
  engine: BrowserEngine;
  profile_name: string;
  state: BrowserSessionState;
  current_url: string;
  allowed_origins: string[];
  observation?: BrowserObservation | null;
  action_count: number;
  trace_path?: string | null;
  created_at: string;
  updated_at: string;
}

export type PortalCapability =
  | "SEARCH"
  | "JOB_EXTRACTION"
  | "APPLICATION_LAUNCH"
  | "MULTI_PAGE_FORM"
  | "DOCUMENT_UPLOAD"
  | "SUBMISSION"
  | "CONFIRMATION";

export interface PortalQualification {
  score: number;
  threshold: number;
  eligible: boolean;
  matched_terms: string[];
  missing_terms: string[];
  evidence_claim_ids: string[];
}

export interface PortalFieldMapping {
  page_type: string;
  canonical_field: string;
  label: string;
  required: boolean;
}

export interface SubmissionEvidence {
  confirmation_code: string;
  confirmation_url: string;
  page_fingerprint: string;
  visible_signal: string;
  verified_at: string;
}

export interface ReferencePortalRunCreate {
  profile_id: string;
  portal_origin: string;
  query: string;
  minimum_fit_score: number;
}

export interface PortalRunSnapshot {
  id: string;
  portal: "REFERENCE_ATS";
  capabilities: PortalCapability[];
  workflow_id: string;
  application_id: string;
  browser_session_id: string;
  profile_id: string;
  job_id: string;
  state: WorkflowState;
  portal_origin: string;
  query: string;
  deduplicated: boolean;
  qualification: PortalQualification;
  selected_document_version_id: string;
  field_mappings: PortalFieldMapping[];
  review_fingerprint: string;
  submission_evidence?: SubmissionEvidence | null;
  trace_path?: string | null;
  created_at: string;
  updated_at: string;
}

export type DocumentKind =
  | "RESUME"
  | "COVER_LETTER"
  | "CERTIFICATION"
  | "EDUCATION"
  | "PORTFOLIO"
  | "OTHER";
export type ClaimVerificationStatus = "PROPOSED" | "VERIFIED" | "REJECTED";
export type ClaimPermittedUse = "PROFILE_ONLY" | "APPLICATIONS" | "ANY";
export type SensitivityLevel = "PUBLIC" | "PERSONAL" | "SENSITIVE";

export interface CandidateDocument {
  id: string;
  profile_id: string;
  kind: DocumentKind;
  display_name: string;
  variant_label: string;
  job_family_tags: string[];
  is_primary: boolean;
  archived: boolean;
  created_at: string;
}

export interface CandidateClaim {
  id: string;
  profile_id: string;
  evidence_source_id?: string | null;
  canonical_key: string;
  statement: string;
  claim_type: string;
  value: Record<string, unknown>;
  source_location?: string | null;
  context: Record<string, unknown>;
  start_date?: string | null;
  end_date?: string | null;
  confidence: number;
  verification_status: ClaimVerificationStatus;
  permitted_use: ClaimPermittedUse;
  sensitivity: SensitivityLevel;
  locked: boolean;
  superseded_by_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AnswerLibraryEntry {
  id: string;
  profile_id: string;
  question: string;
  canonical_field: string;
  answer: string;
  evidence_claim_ids: string[];
  confidence: number;
  approved: boolean;
  locked: boolean;
  reuse_permission: ClaimPermittedUse;
  provenance: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CandidateKnowledgeSnapshot {
  profile_id: string;
  documents: CandidateDocument[];
  claims: CandidateClaim[];
  answers: AnswerLibraryEntry[];
}

export type WorkflowControlAction =
  "ADVANCE" | "PAUSE" | "RESUME" | "RETRY" | "TAKEOVER" | "STOP";

export interface WorkflowRunSnapshot {
  workflow_id: string;
  application_id: string;
  profile_id: string;
  candidate_display_name: string;
  employer: string;
  title: string;
  state: WorkflowState;
  progress: number;
  updated_at: string;
  events: WorkflowEvent[];
}

export interface CandidateProfileCreate {
  display_name: string;
  contact: ContactDetails;
}

export interface MockWorkflowCreate {
  profile_id: string;
  employer: string;
  title: string;
}

export type BackendRuntimeState = "starting" | "ready" | "degraded" | "stopped";

export interface BackendRuntimeStatus {
  state: BackendRuntimeState;
  message: string;
  checked_at: string;
}

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
  workbench: {
    getStatus(): Promise<BackendRuntimeStatus>;
    listWorkflows(): Promise<WorkflowRunSnapshot[]>;
    listBrowserSessions(workflowId?: string): Promise<BrowserSessionSnapshot[]>;
    getCandidateKnowledge(
      profileId: string,
    ): Promise<CandidateKnowledgeSnapshot>;
    selectAndImportResume(
      profileId: string,
    ): Promise<CandidateKnowledgeSnapshot | null>;
    reviewCandidateClaim(
      claimId: string,
      approved: boolean,
    ): Promise<CandidateClaim>;
    createCandidate(input: CandidateProfileCreate): Promise<CandidateProfile>;
    startMockWorkflow(input: MockWorkflowCreate): Promise<WorkflowRunSnapshot>;
    controlWorkflow(
      workflowId: string,
      action: WorkflowControlAction,
    ): Promise<WorkflowRunSnapshot>;
    listPortalRuns(): Promise<PortalRunSnapshot[]>;
    prepareReferencePortal(
      input: ReferencePortalRunCreate,
    ): Promise<PortalRunSnapshot>;
    confirmReferencePortal(
      runId: string,
      reviewFingerprint: string,
    ): Promise<PortalRunSnapshot>;
    onStatus(listener: (status: BackendRuntimeStatus) => void): () => void;
  };
}
