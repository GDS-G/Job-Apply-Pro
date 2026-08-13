export const buildInfo = {
  name: "Observed Form Control Capture",
  version: "0.30.0-alpha.1",
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
export type BrowserActionKind =
  | "NAVIGATE"
  | "CLICK"
  | "FILL"
  | "SELECT"
  | "SELECT_LABEL"
  | "CHECK"
  | "UNCHECK"
  | "UPLOAD"
  | "WAIT_FOR"
  | "SCREENSHOT";

export type BrowserControlKind =
  | "TEXT"
  | "TEXT_AREA"
  | "EMAIL"
  | "TELEPHONE"
  | "NUMBER"
  | "DATE"
  | "SELECT"
  | "RADIO_GROUP"
  | "CHECKBOX"
  | "FILE_UPLOAD"
  | "SIGNATURE"
  | "DISCLOSURE"
  | "BUTTON"
  | "LINK"
  | "CUSTOM";

export interface BrowserControlOption {
  value: string;
  label: string;
  locator?: Record<string, unknown> | null;
}

export interface BrowserObservedControl {
  index: number;
  control_key: string;
  kind: BrowserControlKind;
  tag: string;
  input_type: string;
  role: string;
  element_id: string;
  field_name: string;
  group_label: string;
  label: string;
  label_source: string;
  text: string;
  href: string;
  canonical_field: string;
  accept: string;
  checked: boolean;
  required: boolean;
  native_required: boolean;
  accessible_required: boolean;
  disabled: boolean;
  native_disabled: boolean;
  inherited_disabled: boolean;
  accessible_disabled: boolean;
  read_only: boolean;
  native_read_only: boolean;
  accessible_read_only: boolean;
  busy: boolean;
  control_busy: boolean;
  form_busy: boolean;
  inert: boolean;
  direct_inert: boolean;
  inherited_inert: boolean;
  accessibility_hidden: boolean;
  direct_accessibility_hidden: boolean;
  inherited_accessibility_hidden: boolean;
  visible: boolean;
  will_validate: boolean;
  constraint_satisfied: boolean;
  accessible_invalid: boolean;
  legal_attestation: boolean;
  character_limit?: number | null;
  minimum_number?: number | null;
  maximum_number?: number | null;
  earliest_date?: string | null;
  latest_date?: string | null;
  options: BrowserControlOption[];
  locator?: Record<string, unknown> | null;
}

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
  controls: BrowserObservedControl[];
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
  | "CONFIRMATION"
  | "LOGIN"
  | "MFA"
  | "CAPTCHA"
  | "QUESTIONNAIRE"
  | "ASSESSMENT"
  | "SAVED_JOBS";

export type PortalKind =
  | "REFERENCE_ATS"
  | "LINKEDIN"
  | "INDEED"
  | "MONSTER"
  | "CAREERBUILDER"
  | "DICE"
  | "ZIPRECRUITER"
  | "GLASSDOOR"
  | "COMPANY_CAREERS"
  | "WORKDAY"
  | "TALEO"
  | "GREENHOUSE";

export interface PortalFingerprintRule {
  page_type: string;
  required_signals: string[];
  capability: PortalCapability;
  minimum_confidence: number;
}

export interface PortalAdapterDefinition {
  kind: PortalKind;
  display_name: string;
  domains: string[];
  strategy: "NATIVE_ADAPTER" | "GENERIC_AGENT";
  capabilities: PortalCapability[];
  fingerprints: PortalFingerprintRule[];
  confirmation: {
    page_types: string[];
    required_text_patterns: string[];
    require_identifier: boolean;
  };
  support_status: "REPLAY_VALIDATED" | "LIVE_VALIDATION_REQUIRED" | "DISABLED";
  production_enabled: boolean;
  replay_validated_page_types: string[];
  live_validated_page_types: string[];
  limitations: string[];
  adapter_version: string;
}

export interface PortalPageMatch {
  portal: PortalKind;
  capability: PortalCapability;
  page_type: string;
  confidence: number;
  matched_signals: string[];
  page_fingerprint: string;
  requires_user_intervention: boolean;
}

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

export type SupervisedPortalRunState =
  | "AWAITING_USER"
  | "INTERVENTION_REQUIRED"
  | "READY_TO_SUBMIT"
  | "SUBMISSION_UNCERTAIN"
  | "SUBMISSION_CONFIRMED"
  | "STOPPED";
export type SupervisedPortalDisposition =
  | "USER_ACTION_REQUIRED"
  | "MANUAL_INTERVENTION_REQUIRED"
  | "FINAL_CONFIRMATION_REQUIRED"
  | "CONFIRMATION_VERIFIED"
  | "CONFIRMATION_UNCERTAIN"
  | "STOPPED";
export type PortalInterventionReason =
  | "USER_TAKEOVER"
  | "LOGIN"
  | "MFA"
  | "CAPTCHA"
  | "ASSESSMENT"
  | "LEGAL_ATTESTATION"
  | "FINAL_SUBMISSION"
  | "SITE_CHANGED";

export interface SupervisedPortalRunCreate {
  workflow_id: string;
  portal: PortalKind;
  start_url: string;
  profile_name: string;
  engine: BrowserEngine;
  allowed_origins: string[];
}

export interface SupervisedPortalStepEvidence {
  id: string;
  run_id: string;
  sequence: number;
  disposition: SupervisedPortalDisposition;
  capability?: PortalCapability | null;
  page_type: string;
  before_fingerprint: string;
  after_fingerprint: string;
  action_kind?: BrowserActionKind | null;
  action_fingerprint: string;
  verified: boolean;
  intervention_reasons: PortalInterventionReason[];
  created_at: string;
}

export interface SupervisedPortalRunSnapshot {
  id: string;
  portal: PortalKind;
  workflow_id: string;
  browser_session_id: string;
  state: SupervisedPortalRunState;
  current_url: string;
  allowed_origins: string[];
  page_fingerprint: string;
  current_match?: PortalPageMatch | null;
  disposition: SupervisedPortalDisposition;
  intervention_reasons: PortalInterventionReason[];
  evidence: SupervisedPortalStepEvidence[];
  observed_controls: BrowserObservedControl[];
  trace_path?: string | null;
  created_at: string;
  updated_at: string;
}

export type ChallengeKind = "CAPTCHA" | "QUESTIONNAIRE" | "ASSESSMENT" | "QUIZ";
export type ChallengeStatus =
  | "DETECTED"
  | "INTERVENTION_REQUIRED"
  | "IN_PROGRESS"
  | "REVIEW_REQUIRED"
  | "COMPLETED"
  | "FAILED"
  | "EXPIRED";
export type QuestionKind =
  | "TEXT"
  | "LONG_TEXT"
  | "SELECT"
  | "CHECKBOX"
  | "MULTIPLE_CHOICE"
  | "TRUE_FALSE"
  | "MATCHING"
  | "ORDERING"
  | "VISUAL";
export type AnswerSource =
  "CANDIDATE_PROFILE" | "ANSWER_LIBRARY" | "USER" | "AI_GATEWAY";

export interface ChallengeDetection {
  kind: ChallengeKind;
  page_type: string;
  provider?: string | null;
  captcha_type?: string | null;
  signatures: string[];
  page_fingerprint: string;
  detected_at: string;
}

export interface ChallengeQuestion {
  id: string;
  position: number;
  prompt: string;
  kind: QuestionKind;
  options: string[];
  required: boolean;
  character_limit?: number | null;
  canonical_field?: string | null;
  legal_attestation: boolean;
  signature_required: boolean;
}

export interface ChallengeAnswer {
  question_id: string;
  value: string;
  source: AnswerSource;
  provenance: Record<string, unknown>;
  confidence: number;
  verified: boolean;
  answered_at: string;
}

export interface ChallengeSessionSnapshot {
  id: string;
  workflow_id: string;
  browser_session_id: string;
  resume_state: WorkflowState;
  detection: ChallengeDetection;
  status: ChallengeStatus;
  instructions: string;
  questions: ChallengeQuestion[];
  answers: ChallengeAnswer[];
  current_position: number;
  flagged_question_ids: string[];
  time_limit_seconds?: number | null;
  elapsed_seconds: number;
  remaining_seconds?: number | null;
  review_fingerprint?: string | null;
  completion_signal?: string | null;
  retry_count: number;
  created_at: string;
  updated_at: string;
}

export interface ChallengeSessionCreate {
  workflow_id: string;
  browser_session_id: string;
  time_limit_seconds?: number | null;
}

export interface ChallengeAnswerCommand {
  question_id: string;
  value: string;
  source?: AnswerSource;
  confidence?: number;
}

export interface ChallengeAnswerSuggestion {
  question_id: string;
  value: string;
  source: AnswerSource;
  provenance: Record<string, unknown>;
  confidence: number;
}

export interface ChallengeModelRoute {
  question_id: string;
  tier: "FAST_TEXT" | "STRONG_REASONING" | "MULTIMODAL" | "LONG_CONTEXT";
  task_type: "ANSWER";
  required_capabilities: string[];
  cache_allowed: boolean;
  escalation_reason?: string | null;
}

export type IntegrationProvider =
  "GMAIL" | "OUTLOOK" | "GOOGLE_CALENDAR" | "OUTLOOK_CALENDAR";
export type IntegrationStatus =
  "NOT_CONFIGURED" | "AUTHORIZATION_REQUIRED" | "CONNECTED" | "ERROR";
export type MessageCategory =
  | "RECRUITER_INQUIRY"
  | "INTERVIEW_REQUEST"
  | "SCREENING_REQUEST"
  | "ASSESSMENT_INVITATION"
  | "APPLICATION_CONFIRMATION"
  | "STATUS_UPDATE"
  | "REJECTION"
  | "OFFER"
  | "JOB_ALERT"
  | "NEWSLETTER"
  | "SPAM_OR_UNRELATED";

export interface IntegrationHealth {
  provider: IntegrationProvider;
  status: IntegrationStatus;
  message: string;
  read_enabled: boolean;
  write_enabled: boolean;
  credential_reference?: string | null;
  granted_scopes: string[];
  account_hint?: string | null;
}

export type ProviderConfigurationSource =
  "NOT_CONFIGURED" | "IMPORT_PREVIEW" | "ENVIRONMENT" | "ENCRYPTED_DATABASE";

export interface ProviderConfigurationPreview {
  provider: IntegrationProvider;
  oauth_configured: boolean;
  requested_scopes: string[];
  read_enabled: boolean;
  write_enabled: boolean;
}

export interface ProviderConfigurationStatus {
  source: ProviderConfigurationSource;
  providers: ProviderConfigurationPreview[];
  automatic_categories: MessageCategory[];
  updated_at?: string | null;
}

export interface OAuthAuthorizationRequest {
  provider: IntegrationProvider;
  authorization_url: string;
  state: string;
  expires_at: string;
}

export interface OAuthAuthorizationState {
  provider: IntegrationProvider;
  status: IntegrationStatus;
  credential_reference?: string | null;
  granted_scopes: string[];
  expires_at?: string | null;
  account_hint?: string | null;
}

export interface NormalizedMessage {
  provider: IntegrationProvider;
  provider_message_id: string;
  provider_thread_id: string;
  sender: string;
  recipients: string[];
  subject: string;
  body_text: string;
  received_at: string;
  attachment_names: string[];
  referenced_identifiers: string[];
  referenced_urls: string[];
}

export interface CommunicationRecord {
  id: string;
  analysis: {
    message: NormalizedMessage;
    classification: {
      category: MessageCategory;
      confidence: number;
      matched_signals: string[];
      requires_review: boolean;
    };
    correlation: {
      workflow_id?: string | null;
      confidence: number;
      matched_signals: string[];
      requires_review: boolean;
    };
    reply_draft: {
      subject: string;
      body_text: string;
      category: MessageCategory;
      requires_review: boolean;
      auto_send_allowed: boolean;
      evidence: string[];
    };
    proposed_times: string[];
    time_proposal_requires_review: boolean;
  };
  received_at: string;
  created_at: string;
}

export interface ProviderMessageSyncResult {
  provider: IntegrationProvider;
  fetched_count: number;
  imported_count: number;
  duplicate_count: number;
  record_ids: string[];
  sync_mode: "INITIAL" | "INCREMENTAL" | "RECOVERY";
  cursor_updated_at: string;
}

export interface CalendarEventSnapshot {
  provider_event_id: string;
  title: string;
  start_at: string;
  end_at: string;
  time_zone: string;
  attendees: string[];
  conferencing_url?: string | null;
  location?: string | null;
}

export interface SyncedCalendarEvent {
  provider: IntegrationProvider;
  event: CalendarEventSnapshot;
  synced_at: string;
}

export interface ProviderCalendarSyncResult {
  provider: IntegrationProvider;
  fetched_count: number;
  stored_count: number;
  removed_count: number;
  window_start: string;
  window_end: string;
  synced_at: string;
}

export interface DailyCommunicationSummary {
  generated_at: string;
  analyzed_messages: number;
  review_required: number;
  scheduled_follow_ups: number;
  due_follow_ups: number;
  planned_mutations: number;
  confirmed_mutations: number;
}

export type FollowUpStatus = "SCHEDULED" | "DUE" | "COMPLETED" | "CANCELLED";

export interface FollowUp {
  id: string;
  workflow_id: string;
  reason: string;
  due_at: string;
  channel: IntegrationProvider;
  status: FollowUpStatus;
  dedupe_key: string;
  created_at: string;
  updated_at: string;
}

export type DesktopNotificationKind =
  | "MFA_REQUIRED"
  | "CAPTCHA_REQUIRED"
  | "USER_ACTION_REQUIRED"
  | "ASSESSMENT_REQUIRED"
  | "WORKFLOW_FAILED"
  | "SESSION_EXPIRING"
  | "SESSION_EXPIRED"
  | "RECRUITER_RESPONSE"
  | "INTERVIEW_REQUEST"
  | "INTERVIEW_REMINDER"
  | "OFFER_RECEIVED"
  | "FOLLOW_UP_DUE"
  | "BACKUP_FAILED"
  | "UPDATE_FAILED";

export type DesktopNotificationDestination =
  "WORKFLOWS" | "CHALLENGES" | "COMMUNICATIONS" | "OPERATIONS";

export interface DesktopNotificationItem {
  id: string;
  kind: DesktopNotificationKind;
  title: string;
  body: string;
  destination: DesktopNotificationDestination;
  severity: "info" | "warning" | "critical";
  occurred_at: string;
}

export interface DesktopNotificationStatus {
  native_enabled: boolean;
  native_supported: boolean;
  poll_interval_seconds: number;
  active_notifications: DesktopNotificationItem[];
  delivered_count: number;
  last_checked_at?: string | null;
  last_error?: string | null;
}

export type BackupCategory = "DATABASE" | "DOCUMENTS";
export type BackupStatus = "CREATING" | "VERIFIED" | "FAILED";
export type RestoreStatus = "STAGED" | "APPLIED" | "FAILED";
export type LicenseStatus =
  | "DEVELOPMENT"
  | "ACTIVE"
  | "GRACE_PERIOD"
  | "EXPIRED"
  | "INVALID"
  | "NOT_CONFIGURED";

export interface BackupEntry {
  category: BackupCategory;
  relative_path: string;
  size_bytes: number;
  sha256: string;
}

export interface BackupManifest {
  id: string;
  format_version: number;
  application_version: string;
  schema_revision: string;
  label: string;
  categories: BackupCategory[];
  entries: BackupEntry[];
  encryption_key_id: string;
  archive_path: string;
  archive_sha256: string;
  archive_size_bytes: number;
  status: BackupStatus;
  created_at: string;
  verified_at?: string | null;
}

export interface BackupVerification {
  backup_id: string;
  valid: boolean;
  reasons: string[];
  verified_entries: number;
  verified_at: string;
}

export interface BackupSchedule {
  id: string;
  label: string;
  categories: BackupCategory[];
  interval_hours: number;
  enabled: boolean;
  next_run_at: string;
  last_run_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface RestorePlan {
  id: string;
  backup_id: string;
  categories: BackupCategory[];
  staged_path: string;
  file_count: number;
  fingerprint: string;
  status: RestoreStatus;
  created_at: string;
  applied_at?: string | null;
}

export interface LicenseState {
  status: LicenseStatus;
  message: string;
  entitlement?: {
    license_id: string;
    subject: string;
    device_public_key: string;
    features: string[];
    issued_at: string;
    expires_at: string;
    offline_grace_days: number;
  } | null;
  recovery_allowed: boolean;
  payment_enabled: boolean;
}

export interface HelpTopic {
  id: string;
  title: string;
  summary: string;
  steps: string[];
  context: string;
}

export type UpdateState =
  | "DISABLED"
  | "IDLE"
  | "CHECKING"
  | "AVAILABLE"
  | "DOWNLOADING"
  | "DOWNLOADED"
  | "UP_TO_DATE"
  | "ERROR";

export interface DesktopUpdateStatus {
  state: UpdateState;
  current_version: string;
  available_version?: string | null;
  progress_percent?: number | null;
  message: string;
  checked_at: string;
}

export interface SupportDiagnostics {
  generated_at: string;
  application_version: string;
  build_name: string;
  schema_revision: string;
  environment: string;
  process_status: string;
  queue: { total: number; active: number; retryable: number; terminal: number };
  recovery: {
    retried_actions: number;
    recovered_actions: number;
    recovery_rate: number;
    checkpoint_count: number;
  };
  sessions: {
    active: number;
    takeover: number;
    stopped: number;
    failed: number;
  };
  storage: {
    database_bytes: number;
    documents_bytes: number;
    browser_artifacts_bytes: number;
    backups_bytes: number;
    restore_staging_bytes: number;
  };
  backups_total: number;
  latest_backup_status?: string | null;
  models: OperationsDashboard["models"];
  portals: OperationsDashboard["portals"];
  workflows: {
    workflow_id: string;
    state: string;
    event_count: number;
    updated_at: string;
  }[];
  errors: {
    classification: string;
    component: string;
    action: string;
    retry_count: number;
    context_keys: string[];
    created_at: string;
  }[];
  traces: {
    workflow_id: string;
    file_name: string;
    size_bytes: number;
    available: boolean;
  }[];
  update_status: "MANAGED_BY_DESKTOP";
  redaction_policy_version: string;
}

export interface OperationsDashboard {
  generated_at: string;
  applications: {
    jobs_discovered: number;
    applications_total: number;
    submission_attempted: number;
    submission_confirmed: number;
    tracking_active: number;
    failed: number;
    duplicated: number;
    interviews_received: number;
    offers_received: number;
    recruiter_messages: number;
  };
  models: {
    invocations: number;
    successful: number;
    failed: number;
    input_tokens: number;
    output_tokens: number;
    cost_micros: number;
    average_latency_ms: number;
    by_provider: Record<string, number>;
  };
  portals: {
    portal: string;
    support_status: string;
    production_enabled: boolean;
    run_count: number;
    replay_validated_page_types: string[];
    live_validated_page_types: string[];
    limitations: string[];
  }[];
  application_report: {
    workflow_id: string;
    employer: string;
    title: string;
    state: string;
    submission_attempted: boolean;
    submission_confirmed: boolean;
    updated_at: string;
  }[];
  interview_report: {
    communication_id: string;
    workflow_id?: string | null;
    category: string;
    sender: string;
    subject: string;
    received_at: string;
  }[];
  backup_count: number;
  latest_backup?: BackupManifest | null;
  license: LicenseState;
}

export type DocumentKind =
  | "RESUME"
  | "COVER_LETTER"
  | "CERTIFICATION"
  | "EDUCATION"
  | "PORTFOLIO"
  | "OTHER";
export type DocumentOutputFormat = "DOCX" | "PDF";
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
  revision: number;
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

export interface AnswerLibraryInput {
  question: string;
  canonical_field: string;
  answer: string;
  evidence_claim_ids: string[];
  confidence: number;
  approved: boolean;
  locked: boolean;
  reuse_permission: ClaimPermittedUse;
  provenance: Record<string, unknown>;
}

export interface AnswerLibraryRevision {
  id: string;
  answer_id: string;
  profile_id: string;
  revision: number;
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
}

export type ApplicationAnswerStatus =
  | "NEEDS_REVIEW"
  | "DRAFTED"
  | "REVIEWED"
  | "PROMOTED"
  | "LEGACY_REVIEW_REQUIRED";

export type ApplicationAnswerSource =
  "UNANSWERED" | "LIBRARY_REUSE" | "GOVERNED_AI" | "USER_REVIEWED" | "LEGACY";

export type ApplicationAnswerKind =
  | "EXACT"
  | "SHORT_TEXT"
  | "LONG_TEXT"
  | "NUMBER"
  | "DATE"
  | "YES_NO"
  | "MULTIPLE_CHOICE"
  | "SALARY"
  | "AVAILABILITY"
  | "TECHNOLOGY_EXPERIENCE"
  | "BEHAVIORAL"
  | "EMPLOYER_SPECIFIC";

export interface ApplicationAnswerDraftInput {
  application_id: string;
  question: string;
  canonical_field: string;
  answer_kind: ApplicationAnswerKind;
  choices: string[];
  minimum_number?: number | null;
  maximum_number?: number | null;
  earliest_date?: string | null;
  latest_date?: string | null;
  character_limit: number;
  allow_ai: boolean;
  external_ai_consent: boolean;
  reuse_permission: ClaimPermittedUse;
}

export interface ApplicationAnswer {
  id: string;
  application_id: string;
  profile_id: string;
  job_id: string;
  revision: number;
  question: string;
  normalized_question: string;
  canonical_field: string;
  answer_kind: ApplicationAnswerKind;
  validation_rules: Record<string, unknown>;
  answer?: string | null;
  status: ApplicationAnswerStatus;
  source_type: ApplicationAnswerSource;
  source_answer_id?: string | null;
  library_answer_id?: string | null;
  evidence_claim_ids: string[];
  retrieval_results: Record<string, unknown>[];
  provider_id?: string | null;
  model_id?: string | null;
  prompt_version?: string | null;
  policy_version: string;
  confidence: number;
  character_limit: number;
  character_limit_applied: boolean;
  limitations: string[];
  user_edited: boolean;
  reuse_permission: ClaimPermittedUse;
  created_at: string;
  updated_at: string;
}

export interface ApplicationAnswerReviewInput {
  answer: string;
  evidence_claim_ids: string[];
  confidence: number;
  reuse_permission: ClaimPermittedUse;
}

export type PortalFieldControlKind =
  | "TEXT"
  | "TEXT_AREA"
  | "EMAIL"
  | "TELEPHONE"
  | "NUMBER"
  | "DATE"
  | "SELECT"
  | "RADIO_GROUP"
  | "CHECKBOX"
  | "FILE_UPLOAD"
  | "SIGNATURE"
  | "DISCLOSURE"
  | "CUSTOM";

export type FieldAutomationPermission =
  "PROHIBITED" | "REVIEW_REQUIRED" | "AUTOFILL_ALLOWED";

export interface ObservedPortalField {
  portal: string;
  page_fingerprint: string;
  control_key: string;
  control_kind: PortalFieldControlKind;
  label: string;
  required: boolean;
  options: string[];
  character_limit?: number | null;
  minimum_number?: number | null;
  maximum_number?: number | null;
  earliest_date?: string | null;
  latest_date?: string | null;
  legal_attestation: boolean;
}

export interface ApplicationFieldBindingPreviewInput {
  application_answer_id: string;
  observed_field: ObservedPortalField;
}

export interface ApplicationFieldBindingPreview {
  application_id: string;
  application_answer_id: string;
  answer_revision: number;
  portal: string;
  page_fingerprint: string;
  control_key: string;
  control_kind: PortalFieldControlKind;
  label: string;
  required: boolean;
  options: string[];
  canonical_field: string;
  confidence: number;
  binding_source:
    "EXACT_CANONICAL_MATCH" | "ANSWER_QUESTION_MATCH" | "USER_CONFIRMED";
  answer_source: ApplicationAnswerSource;
  answer_status: ApplicationAnswerStatus;
  answer_kind: ApplicationAnswerKind;
  validation_rules: Record<string, unknown>;
  compatible: boolean;
  validation_errors: string[];
  proposed_permission: FieldAutomationPermission;
  review_fingerprint: string;
}

export interface ApplicationFieldBinding extends Omit<
  ApplicationFieldBindingPreview,
  "answer_status" | "compatible" | "validation_errors" | "proposed_permission"
> {
  id: string;
  binding_source: "USER_CONFIRMED";
  automation_permission: Exclude<FieldAutomationPermission, "PROHIBITED">;
  created_at: string;
  updated_at: string;
}

export interface ApplicationFieldExecution {
  id: string;
  binding_id: string;
  application_id: string;
  application_answer_id: string;
  answer_revision: number;
  supervised_run_id: string;
  browser_session_id: string;
  portal: string;
  page_fingerprint_before: string;
  page_fingerprint_after: string;
  control_key: string;
  action_kind: "FILL" | "SELECT" | "SELECT_LABEL" | "CHECK" | "UNCHECK";
  verified: boolean;
  action_fingerprint: string;
  error?: string | null;
  created_at: string;
}

export type ApplicationFieldCoverageStatus =
  | "SATISFIED_ON_PAGE"
  | "READY_TO_EXECUTE"
  | "ALREADY_VERIFIED"
  | "MANUAL_REQUIRED"
  | "UNBOUND"
  | "STALE_BINDING"
  | "AMBIGUOUS_BINDING";

export interface ApplicationFieldCoverageItem {
  control_key: string;
  label: string;
  control_kind: PortalFieldControlKind;
  required: true;
  status: ApplicationFieldCoverageStatus;
  binding_id?: string | null;
  reason: string;
}

export interface ApplicationFieldCoverageReview {
  application_id: string;
  supervised_run_id: string;
  portal: string;
  page_fingerprint: string;
  required_control_count: number;
  satisfied_on_page_count: number;
  ready_to_execute_count: number;
  already_verified_count: number;
  manual_required_count: number;
  unbound_count: number;
  stale_binding_count: number;
  ambiguous_binding_count: number;
  items: ApplicationFieldCoverageItem[];
  review_fingerprint: string;
}

export interface CandidateKnowledgeSnapshot {
  profile_id: string;
  documents: CandidateDocument[];
  claims: CandidateClaim[];
  answers: AnswerLibraryEntry[];
}

export interface DocumentLayoutBlock {
  index: number;
  page?: number | null;
  row?: number | null;
  column?: number | null;
  table?: number | null;
  kind: string;
  style?: string | null;
  text: string;
}

export interface DocumentExtraction {
  parser: string;
  plain_text: string;
  blocks: DocumentLayoutBlock[];
  page_count: number;
  character_count: number;
  warnings: string[];
}

export interface CandidateDocumentImportResult {
  snapshot: CandidateKnowledgeSnapshot;
  extraction: DocumentExtraction;
}

export interface CandidateDocumentImportInput {
  variant_label: string;
  job_family_tags: string[];
  is_primary: boolean;
}

export interface DocumentSelectionRequest {
  application_id: string;
  kind: "RESUME";
  preferred_tags: string[];
  excluded_document_ids: string[];
  prefer_primary: boolean;
}

export interface DocumentRecommendation {
  document_id: string;
  document_version_id: string;
  display_name: string;
  variant_label: string;
  score: number;
  matched_job_family_tags: string[];
  matched_requirement_ids: string[];
  reasons: string[];
  is_primary: boolean;
}

export interface DocumentSelectionPreview {
  application_id: string;
  profile_id: string;
  job_id: string;
  employer: string;
  title: string;
  current_document_version_id?: string | null;
  recommended_document_version_id: string;
  recommendations: DocumentRecommendation[];
  review_fingerprint: string;
}

export interface DocumentSelectionAudit {
  id: string;
  application_id: string;
  profile_id: string;
  job_id: string;
  document_id: string;
  document_version_id: string;
  score: number;
  review_fingerprint: string;
  criteria: Record<string, unknown>;
  reasons: string[];
  created_at: string;
}

export interface TailoredDocumentRequest {
  application_id: string;
  kind: "RESUME" | "COVER_LETTER";
  output_format: DocumentOutputFormat;
  variant_label: string;
  max_claims: number;
  template: "PROFESSIONAL" | "COMPACT";
  ranking_mode: "DETERMINISTIC" | "GOVERNED_AI";
  external_ai_consent: boolean;
}

export interface TailoredDocumentSection {
  heading: string;
  paragraphs: string[];
  evidence_claim_ids: string[];
}

export interface TailoredDocumentPreview {
  application_id: string;
  profile_id: string;
  job_id: string;
  kind: "RESUME" | "COVER_LETTER";
  output_format: DocumentOutputFormat;
  employer: string;
  title: string;
  variant_label: string;
  template: "PROFESSIONAL" | "COMPACT";
  ranking_mode: "DETERMINISTIC" | "GOVERNED_AI";
  ranking_method: string;
  ranking_notice?: string | null;
  sections: TailoredDocumentSection[];
  selected_claim_ids: string[];
  matched_requirement_ids: string[];
  missing_required_requirements: string[];
  review_fingerprint: string;
}

export interface DocumentGenerationAudit {
  id: string;
  application_id: string;
  profile_id: string;
  job_id: string;
  document_version_id: string;
  kind: "RESUME" | "COVER_LETTER";
  output_format: DocumentOutputFormat;
  template: "PROFESSIONAL" | "COMPACT";
  ranking_mode: "DETERMINISTIC" | "GOVERNED_AI";
  ranking_method: string;
  review_fingerprint: string;
  evidence_claim_ids: string[];
  requirement_ids: string[];
  missing_required_requirements: string[];
  created_at: string;
}

export interface TailoredDocumentResult {
  preview: TailoredDocumentPreview;
  document: CandidateDocument;
  version: {
    id: string;
    document_id: string;
    version: number;
    file_name: string;
    media_type: string;
    sha256: string;
    parser_version: string;
    page_count: number;
    character_count: number;
    created_at: string;
  };
  audit: DocumentGenerationAudit;
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
      input: CandidateDocumentImportInput,
    ): Promise<CandidateDocumentImportResult | null>;
    previewDocumentSelection(
      input: DocumentSelectionRequest,
    ): Promise<DocumentSelectionPreview>;
    approveDocumentSelection(
      input: DocumentSelectionRequest,
      documentVersionId: string,
      reviewFingerprint: string,
    ): Promise<DocumentSelectionAudit | null>;
    reviewCandidateClaim(
      claimId: string,
      approved: boolean,
    ): Promise<CandidateClaim>;
    createAnswer(
      profileId: string,
      input: AnswerLibraryInput,
    ): Promise<AnswerLibraryEntry | null>;
    updateAnswer(
      answerId: string,
      expectedRevision: number,
      input: AnswerLibraryInput,
    ): Promise<AnswerLibraryEntry | null>;
    listAnswerRevisions(answerId: string): Promise<AnswerLibraryRevision[]>;
    draftApplicationAnswer(
      input: ApplicationAnswerDraftInput,
    ): Promise<ApplicationAnswer>;
    listApplicationAnswers(applicationId: string): Promise<ApplicationAnswer[]>;
    reviewApplicationAnswer(
      answerId: string,
      expectedRevision: number,
      input: ApplicationAnswerReviewInput,
    ): Promise<ApplicationAnswer | null>;
    promoteApplicationAnswer(
      answerId: string,
      expectedRevision: number,
    ): Promise<ApplicationAnswer | null>;
    previewApplicationFieldBinding(
      input: ApplicationFieldBindingPreviewInput,
    ): Promise<ApplicationFieldBindingPreview>;
    approveApplicationFieldBinding(
      input: ApplicationFieldBindingPreviewInput,
      expectedAnswerRevision: number,
      reviewFingerprint: string,
      automationPermission: Exclude<FieldAutomationPermission, "PROHIBITED">,
    ): Promise<ApplicationFieldBinding | null>;
    listApplicationFieldBindings(
      applicationId: string,
    ): Promise<ApplicationFieldBinding[]>;
    executeApplicationField(
      runId: string,
      bindingId: string,
      reviewPageFingerprint: string,
    ): Promise<ApplicationFieldExecution | null>;
    listApplicationFieldExecutions(
      applicationId: string,
    ): Promise<ApplicationFieldExecution[]>;
    reviewApplicationFieldCoverage(
      runId: string,
      applicationId: string,
    ): Promise<ApplicationFieldCoverageReview>;
    previewTailoredDocument(
      input: TailoredDocumentRequest,
    ): Promise<TailoredDocumentPreview>;
    generateTailoredDocument(
      input: TailoredDocumentRequest,
      reviewFingerprint: string,
    ): Promise<TailoredDocumentResult | null>;
    createCandidate(input: CandidateProfileCreate): Promise<CandidateProfile>;
    startMockWorkflow(input: MockWorkflowCreate): Promise<WorkflowRunSnapshot>;
    controlWorkflow(
      workflowId: string,
      action: WorkflowControlAction,
    ): Promise<WorkflowRunSnapshot>;
    listPortalRuns(): Promise<PortalRunSnapshot[]>;
    listPortalCatalog(): Promise<PortalAdapterDefinition[]>;
    prepareReferencePortal(
      input: ReferencePortalRunCreate,
    ): Promise<PortalRunSnapshot>;
    confirmReferencePortal(
      runId: string,
      reviewFingerprint: string,
    ): Promise<PortalRunSnapshot>;
    listSupervisedPortalRuns(): Promise<SupervisedPortalRunSnapshot[]>;
    startSupervisedPortal(
      input: SupervisedPortalRunCreate,
    ): Promise<SupervisedPortalRunSnapshot>;
    captureSupervisedPortal(
      runId: string,
      priorPageFingerprint: string,
    ): Promise<SupervisedPortalRunSnapshot>;
    submitSupervisedPortal(
      runId: string,
      reviewFingerprint: string,
    ): Promise<SupervisedPortalRunSnapshot | null>;
    stopSupervisedPortal(runId: string): Promise<SupervisedPortalRunSnapshot>;
    listChallengeSessions(
      workflowId?: string,
    ): Promise<ChallengeSessionSnapshot[]>;
    detectChallenge(
      input: ChallengeSessionCreate,
    ): Promise<ChallengeSessionSnapshot>;
    getChallengeSuggestions(
      sessionId: string,
    ): Promise<ChallengeAnswerSuggestion[]>;
    getChallengeModelRoutes(sessionId: string): Promise<ChallengeModelRoute[]>;
    refreshChallenge(sessionId: string): Promise<ChallengeSessionSnapshot>;
    answerChallenge(
      sessionId: string,
      input: ChallengeAnswerCommand,
    ): Promise<ChallengeSessionSnapshot>;
    completeChallenge(
      sessionId: string,
      reviewFingerprint: string,
    ): Promise<ChallengeSessionSnapshot>;
    completeChallengeIntervention(
      sessionId: string,
      priorFingerprint: string,
    ): Promise<ChallengeSessionSnapshot>;
    listIntegrationHealth(): Promise<IntegrationHealth[]>;
    getProviderConfigurationStatus(): Promise<ProviderConfigurationStatus>;
    selectAndImportProviderConfiguration(): Promise<ProviderConfigurationStatus | null>;
    clearProviderConfiguration(): Promise<ProviderConfigurationStatus | null>;
    startProviderAuthorization(
      provider: IntegrationProvider,
    ): Promise<OAuthAuthorizationRequest>;
    revokeProviderAuthorization(
      provider: IntegrationProvider,
    ): Promise<OAuthAuthorizationState>;
    syncProviderMessages(
      provider: IntegrationProvider,
    ): Promise<ProviderMessageSyncResult>;
    syncProviderCalendar(
      provider: IntegrationProvider,
    ): Promise<ProviderCalendarSyncResult>;
    listSyncedCalendarEvents(): Promise<SyncedCalendarEvent[]>;
    listCommunicationRecords(): Promise<CommunicationRecord[]>;
    getDailyCommunicationSummary(): Promise<DailyCommunicationSummary>;
    getDesktopNotificationStatus(): Promise<DesktopNotificationStatus>;
    refreshDesktopNotifications(): Promise<DesktopNotificationStatus>;
    setNativeNotificationsEnabled(
      enabled: boolean,
    ): Promise<DesktopNotificationStatus>;
    getOperationsDashboard(): Promise<OperationsDashboard>;
    listBackups(): Promise<BackupManifest[]>;
    listBackupSchedules(): Promise<BackupSchedule[]>;
    createBackup(label: string): Promise<BackupManifest>;
    createBackupSchedule(
      label: string,
      intervalHours: number,
    ): Promise<BackupSchedule>;
    verifyBackup(backupId: string): Promise<BackupVerification>;
    stageRestore(backupId: string): Promise<RestorePlan>;
    applyRestore(planId: string, fingerprint: string): Promise<boolean>;
    listHelpTopics(): Promise<HelpTopic[]>;
    exportSupportDiagnostics(): Promise<string | null>;
    getUpdateStatus(): Promise<DesktopUpdateStatus>;
    checkForUpdates(): Promise<DesktopUpdateStatus>;
    downloadUpdate(): Promise<DesktopUpdateStatus>;
    installUpdate(): Promise<void>;
    onUpdateStatus(listener: (status: DesktopUpdateStatus) => void): () => void;
    onDesktopNotificationStatus(
      listener: (status: DesktopNotificationStatus) => void,
    ): () => void;
    onDesktopNotificationActivated(
      listener: (destination: DesktopNotificationDestination) => void,
    ): () => void;
    onStatus(listener: (status: BackendRuntimeStatus) => void): () => void;
  };
}
