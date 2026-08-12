import { writeFile } from "node:fs/promises";
import { arch, platform, release } from "node:os";

import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";

import type {
  ApplicationAnswerDraftInput,
  ApplicationAnswerReviewInput,
  ApplicationFieldBindingPreviewInput,
  FieldAutomationPermission,
  AnswerLibraryInput,
  CandidateDocumentImportInput,
  CandidateProfileCreate,
  ChallengeAnswerCommand,
  ChallengeSessionCreate,
  IntegrationProvider,
  DocumentSelectionRequest,
  MockWorkflowCreate,
  PortalKind,
  ReferencePortalRunCreate,
  SupervisedPortalRunCreate,
  TailoredDocumentRequest,
  WorkflowControlAction,
} from "@job-apply-pro/contracts";

import type { BackendSupervisor } from "./backend-supervisor.js";
import type { DesktopNotificationManager } from "./notification-manager.js";
import { readProviderConfigurationFile } from "./provider-configuration-file.js";
import type { UpdateManager } from "./update-manager.js";

const actions = new Set<WorkflowControlAction>([
  "ADVANCE",
  "PAUSE",
  "RESUME",
  "RETRY",
  "TAKEOVER",
  "STOP",
]);
const integrationProviders = new Set<IntegrationProvider>([
  "GMAIL",
  "OUTLOOK",
  "GOOGLE_CALENDAR",
  "OUTLOOK_CALENDAR",
]);
const supervisedPortals = new Set<PortalKind>([
  "LINKEDIN",
  "INDEED",
  "MONSTER",
  "CAREERBUILDER",
  "DICE",
  "ZIPRECRUITER",
  "GLASSDOOR",
  "COMPANY_CAREERS",
  "WORKDAY",
  "TALEO",
  "GREENHOUSE",
]);
const permittedUses = new Set(["PROFILE_ONLY", "APPLICATIONS", "ANY"]);
const portalFieldControlKinds = new Set([
  "TEXT",
  "TEXT_AREA",
  "EMAIL",
  "TELEPHONE",
  "NUMBER",
  "DATE",
  "SELECT",
  "RADIO_GROUP",
  "CHECKBOX",
  "FILE_UPLOAD",
  "SIGNATURE",
  "DISCLOSURE",
  "CUSTOM",
]);

function requiredText(value: unknown, name: string, maxLength: number): string {
  if (
    typeof value !== "string" ||
    value.trim().length === 0 ||
    value.length > maxLength
  ) {
    throw new TypeError(
      `${name} must be a non-empty string up to ${maxLength} characters.`,
    );
  }
  return value.trim();
}

function integrationProvider(value: unknown): IntegrationProvider {
  if (
    typeof value !== "string" ||
    !integrationProviders.has(value as IntegrationProvider)
  ) {
    throw new TypeError("Integration provider is invalid.");
  }
  return value as IntegrationProvider;
}

function candidateInput(value: unknown): CandidateProfileCreate {
  if (typeof value !== "object" || value === null || !("contact" in value)) {
    throw new TypeError("Candidate profile input is invalid.");
  }
  const contact = value.contact;
  if (typeof contact !== "object" || contact === null) {
    throw new TypeError("Candidate contact input is invalid.");
  }
  return {
    display_name: requiredText(
      Reflect.get(value, "display_name"),
      "Display name",
      200,
    ),
    contact: {
      full_name: requiredText(
        Reflect.get(contact, "full_name"),
        "Full name",
        200,
      ),
      email: requiredText(Reflect.get(contact, "email"), "Email", 320),
      phone: null,
      address: null,
    },
  };
}

function mockWorkflowInput(value: unknown): MockWorkflowCreate {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Mock workflow input is invalid.");
  }
  return {
    profile_id: requiredText(
      Reflect.get(value, "profile_id"),
      "Profile id",
      100,
    ),
    employer: requiredText(Reflect.get(value, "employer"), "Employer", 200),
    title: requiredText(Reflect.get(value, "title"), "Title", 200),
  };
}

function answerLibraryInput(value: unknown): AnswerLibraryInput {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Answer-library input is invalid.");
  }
  const evidence = Reflect.get(value, "evidence_claim_ids");
  if (
    !Array.isArray(evidence) ||
    evidence.length > 50 ||
    !evidence.every((item) => typeof item === "string" && item.length <= 100)
  ) {
    throw new TypeError("Answer evidence must contain at most 50 claim ids.");
  }
  const confidence = Reflect.get(value, "confidence");
  if (typeof confidence !== "number" || confidence < 0 || confidence > 1) {
    throw new TypeError("Answer confidence must be between 0 and 1.");
  }
  const reusePermission = requiredText(
    Reflect.get(value, "reuse_permission"),
    "Reuse permission",
    30,
  );
  if (!permittedUses.has(reusePermission)) {
    throw new TypeError("Answer reuse permission is invalid.");
  }
  return {
    question: requiredText(Reflect.get(value, "question"), "Question", 2_000),
    canonical_field: requiredText(
      Reflect.get(value, "canonical_field"),
      "Canonical field",
      160,
    ),
    answer: requiredText(Reflect.get(value, "answer"), "Answer", 20_000),
    evidence_claim_ids: evidence,
    confidence,
    approved: Reflect.get(value, "approved") === true,
    locked: Reflect.get(value, "locked") === true,
    reuse_permission: reusePermission as AnswerLibraryInput["reuse_permission"],
    provenance: {},
  };
}

function applicationAnswerDraftInput(
  value: unknown,
): ApplicationAnswerDraftInput {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Application-answer draft input is invalid.");
  }
  const characterLimit = Reflect.get(value, "character_limit");
  if (
    typeof characterLimit !== "number" ||
    !Number.isInteger(characterLimit) ||
    characterLimit < 1 ||
    characterLimit > 20_000
  ) {
    throw new TypeError("Character limit must be an integer from 1 to 20000.");
  }
  const reusePermission = requiredText(
    Reflect.get(value, "reuse_permission"),
    "Reuse permission",
    30,
  );
  if (!permittedUses.has(reusePermission)) {
    throw new TypeError("Application-answer reuse permission is invalid.");
  }
  const answerKinds = new Set([
    "EXACT",
    "SHORT_TEXT",
    "LONG_TEXT",
    "NUMBER",
    "DATE",
    "YES_NO",
    "MULTIPLE_CHOICE",
    "SALARY",
    "AVAILABILITY",
    "TECHNOLOGY_EXPERIENCE",
    "BEHAVIORAL",
    "EMPLOYER_SPECIFIC",
  ]);
  const answerKind = requiredText(
    Reflect.get(value, "answer_kind"),
    "Answer kind",
    40,
  );
  if (!answerKinds.has(answerKind)) {
    throw new TypeError("Application-answer kind is invalid.");
  }
  const choicesValue = Reflect.get(value, "choices");
  if (!Array.isArray(choicesValue) || choicesValue.length > 100) {
    throw new TypeError("Application-answer choices are invalid.");
  }
  const choices = choicesValue.map((choice) =>
    requiredText(choice, "Answer choice", 500),
  );
  const optionalNumber = (name: string): number | null => {
    const candidate = Reflect.get(value, name);
    if (candidate === undefined || candidate === null) return null;
    if (typeof candidate !== "number" || !Number.isFinite(candidate)) {
      throw new TypeError(`${name.replaceAll("_", " ")} is invalid.`);
    }
    return candidate;
  };
  const optionalDate = (name: string): string | null => {
    const candidate = Reflect.get(value, name);
    if (candidate === undefined || candidate === null || candidate === "")
      return null;
    const date = requiredText(candidate, name.replaceAll("_", " "), 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      throw new TypeError(`${name.replaceAll("_", " ")} must use YYYY-MM-DD.`);
    }
    return date;
  };
  return {
    application_id: requiredText(
      Reflect.get(value, "application_id"),
      "Application id",
      100,
    ),
    question: requiredText(Reflect.get(value, "question"), "Question", 2_000),
    canonical_field: requiredText(
      Reflect.get(value, "canonical_field"),
      "Canonical field",
      160,
    ),
    answer_kind: answerKind as ApplicationAnswerDraftInput["answer_kind"],
    choices,
    minimum_number: optionalNumber("minimum_number"),
    maximum_number: optionalNumber("maximum_number"),
    earliest_date: optionalDate("earliest_date"),
    latest_date: optionalDate("latest_date"),
    character_limit: characterLimit,
    allow_ai: Reflect.get(value, "allow_ai") === true,
    external_ai_consent: Reflect.get(value, "external_ai_consent") === true,
    reuse_permission:
      reusePermission as ApplicationAnswerDraftInput["reuse_permission"],
  };
}

function applicationAnswerReviewInput(
  value: unknown,
): ApplicationAnswerReviewInput {
  const input = answerLibraryInput({
    ...(typeof value === "object" && value !== null ? value : {}),
    question: "review",
    canonical_field: "review",
    approved: true,
    locked: true,
  });
  return {
    answer: input.answer,
    evidence_claim_ids: input.evidence_claim_ids,
    confidence: input.confidence,
    reuse_permission: input.reuse_permission,
  };
}

function expectedRevision(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    throw new TypeError("Expected answer revision is invalid.");
  }
  return value;
}

function applicationFieldBindingInput(
  value: unknown,
): ApplicationFieldBindingPreviewInput {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Field-binding input is invalid.");
  }
  const field = Reflect.get(value, "observed_field");
  if (typeof field !== "object" || field === null) {
    throw new TypeError("Observed portal field is invalid.");
  }
  const controlKind = requiredText(
    Reflect.get(field, "control_kind"),
    "Control kind",
    40,
  );
  if (!portalFieldControlKinds.has(controlKind)) {
    throw new TypeError("Observed control kind is invalid.");
  }
  const optionsValue = Reflect.get(field, "options");
  if (!Array.isArray(optionsValue) || optionsValue.length > 100) {
    throw new TypeError("Observed options are invalid.");
  }
  const optionalNumber = (name: string): number | null => {
    const candidate = Reflect.get(field, name);
    if (candidate === undefined || candidate === null) return null;
    if (typeof candidate !== "number" || !Number.isFinite(candidate)) {
      throw new TypeError(`${name.replaceAll("_", " ")} is invalid.`);
    }
    return candidate;
  };
  const optionalDate = (name: string): string | null => {
    const candidate = Reflect.get(field, name);
    if (candidate === undefined || candidate === null || candidate === "")
      return null;
    const result = requiredText(candidate, name.replaceAll("_", " "), 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(result)) {
      throw new TypeError(`${name.replaceAll("_", " ")} must use YYYY-MM-DD.`);
    }
    return result;
  };
  const characterLimit = optionalNumber("character_limit");
  if (
    characterLimit !== null &&
    (!Number.isInteger(characterLimit) ||
      characterLimit < 1 ||
      characterLimit > 20_000)
  ) {
    throw new TypeError("Observed character limit is invalid.");
  }
  return {
    application_answer_id: requiredText(
      Reflect.get(value, "application_answer_id"),
      "Application answer id",
      100,
    ),
    observed_field: {
      portal: requiredText(Reflect.get(field, "portal"), "Portal", 80),
      page_fingerprint: requiredText(
        Reflect.get(field, "page_fingerprint"),
        "Page fingerprint",
        200,
      ),
      control_key: requiredText(
        Reflect.get(field, "control_key"),
        "Control key",
        200,
      ),
      control_kind:
        controlKind as ApplicationFieldBindingPreviewInput["observed_field"]["control_kind"],
      label: requiredText(Reflect.get(field, "label"), "Field label", 500),
      required: Reflect.get(field, "required") === true,
      options: optionsValue.map((option) =>
        requiredText(option, "Observed option", 500),
      ),
      character_limit: characterLimit,
      minimum_number: optionalNumber("minimum_number"),
      maximum_number: optionalNumber("maximum_number"),
      earliest_date: optionalDate("earliest_date"),
      latest_date: optionalDate("latest_date"),
      legal_attestation: Reflect.get(field, "legal_attestation") === true,
    },
  };
}

function referencePortalInput(value: unknown): ReferencePortalRunCreate {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Reference portal input is invalid.");
  }
  const portalOrigin = requiredText(
    Reflect.get(value, "portal_origin"),
    "Portal origin",
    2_000,
  );
  const parsed = new URL(portalOrigin);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new TypeError("Portal origin must use HTTP or HTTPS.");
  }
  return {
    profile_id: requiredText(
      Reflect.get(value, "profile_id"),
      "Profile id",
      100,
    ),
    portal_origin: parsed.origin,
    query: requiredText(Reflect.get(value, "query"), "Job query", 200),
    minimum_fit_score: 0.5,
  };
}

function supervisedPortalInput(value: unknown): SupervisedPortalRunCreate {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Supervised portal input is invalid.");
  }
  const portalValue = requiredText(Reflect.get(value, "portal"), "Portal", 40);
  if (!supervisedPortals.has(portalValue as PortalKind)) {
    throw new TypeError("Portal is not available for supervised execution.");
  }
  const startUrl = new URL(
    requiredText(Reflect.get(value, "start_url"), "Start URL", 2_000),
  );
  const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(
    startUrl.hostname,
  );
  if (
    startUrl.protocol !== "https:" &&
    !(startUrl.protocol === "http:" && loopback)
  ) {
    throw new TypeError("External supervised portal URLs must use HTTPS.");
  }
  const originsValue = Reflect.get(value, "allowed_origins");
  if (!Array.isArray(originsValue) || originsValue.length > 20) {
    throw new TypeError("Allowed origins must be an array of at most 20 URLs.");
  }
  const allowedOrigins = originsValue.map((item) => {
    const parsed = new URL(requiredText(item, "Allowed origin", 2_000));
    const isLoopback = ["127.0.0.1", "localhost", "[::1]"].includes(
      parsed.hostname,
    );
    if (
      parsed.protocol !== "https:" &&
      !(parsed.protocol === "http:" && isLoopback)
    ) {
      throw new TypeError("External supervised origins must use HTTPS.");
    }
    return parsed.origin;
  });
  const engine = Reflect.get(value, "engine");
  if (!new Set(["chromium", "chrome", "msedge"]).has(String(engine))) {
    throw new TypeError("Browser engine is invalid.");
  }
  return {
    workflow_id: requiredText(
      Reflect.get(value, "workflow_id"),
      "Workflow id",
      100,
    ),
    portal: portalValue as PortalKind,
    start_url: startUrl.toString(),
    profile_name: requiredText(
      Reflect.get(value, "profile_name"),
      "Browser profile",
      80,
    ),
    engine: engine as SupervisedPortalRunCreate["engine"],
    allowed_origins: allowedOrigins,
  };
}

function tailoredDocumentInput(value: unknown): TailoredDocumentRequest {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Tailored document input is invalid.");
  }
  const kind = requiredText(Reflect.get(value, "kind"), "Document kind", 30);
  if (!new Set(["RESUME", "COVER_LETTER"]).has(kind)) {
    throw new TypeError("Tailored document kind is invalid.");
  }
  const outputFormat = requiredText(
    Reflect.get(value, "output_format"),
    "Output format",
    20,
  );
  if (!new Set(["DOCX", "PDF"]).has(outputFormat)) {
    throw new TypeError("Tailored document output format is invalid.");
  }
  const maxClaims = Reflect.get(value, "max_claims");
  const template = requiredText(
    Reflect.get(value, "template"),
    "Document template",
    30,
  );
  if (!new Set(["PROFESSIONAL", "COMPACT"]).has(template)) {
    throw new TypeError("Tailored document template is invalid.");
  }
  const rankingMode = requiredText(
    Reflect.get(value, "ranking_mode"),
    "Ranking mode",
    30,
  );
  if (!new Set(["DETERMINISTIC", "GOVERNED_AI"]).has(rankingMode)) {
    throw new TypeError("Tailored document ranking mode is invalid.");
  }
  const externalAIConsent = Reflect.get(value, "external_ai_consent");
  if (typeof externalAIConsent !== "boolean") {
    throw new TypeError("External AI consent is invalid.");
  }
  if (
    typeof maxClaims !== "number" ||
    !Number.isInteger(maxClaims) ||
    maxClaims < 1 ||
    maxClaims > 30
  ) {
    throw new TypeError("Tailored document claim limit must be 1 to 30.");
  }
  return {
    application_id: requiredText(
      Reflect.get(value, "application_id"),
      "Application id",
      100,
    ),
    kind: kind as TailoredDocumentRequest["kind"],
    output_format: outputFormat as TailoredDocumentRequest["output_format"],
    variant_label: requiredText(
      Reflect.get(value, "variant_label"),
      "Variant label",
      120,
    ),
    max_claims: maxClaims,
    template: template as TailoredDocumentRequest["template"],
    ranking_mode: rankingMode as TailoredDocumentRequest["ranking_mode"],
    external_ai_consent: externalAIConsent,
  };
}

function documentImportInput(value: unknown): CandidateDocumentImportInput {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Document import metadata is invalid.");
  }
  const tagsValue = Reflect.get(value, "job_family_tags");
  if (!Array.isArray(tagsValue) || tagsValue.length > 30) {
    throw new TypeError(
      "Job-family tags must be an array of at most 30 values.",
    );
  }
  const tags = [
    ...new Set(
      tagsValue.map((item) => requiredText(item, "Job-family tag", 80)),
    ),
  ];
  const isPrimary = Reflect.get(value, "is_primary");
  if (typeof isPrimary !== "boolean") {
    throw new TypeError("Primary-document preference is invalid.");
  }
  return {
    variant_label: requiredText(
      Reflect.get(value, "variant_label"),
      "Variant label",
      120,
    ),
    job_family_tags: tags,
    is_primary: isPrimary,
  };
}

function documentSelectionInput(value: unknown): DocumentSelectionRequest {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Document selection input is invalid.");
  }
  const preferredValue = Reflect.get(value, "preferred_tags");
  const excludedValue = Reflect.get(value, "excluded_document_ids");
  const preferPrimary = Reflect.get(value, "prefer_primary");
  if (!Array.isArray(preferredValue) || preferredValue.length > 30) {
    throw new TypeError(
      "Preferred tags must be an array of at most 30 values.",
    );
  }
  if (!Array.isArray(excludedValue) || excludedValue.length > 100) {
    throw new TypeError(
      "Excluded documents must be an array of at most 100 ids.",
    );
  }
  if (typeof preferPrimary !== "boolean") {
    throw new TypeError("Primary-document preference is invalid.");
  }
  return {
    application_id: requiredText(
      Reflect.get(value, "application_id"),
      "Application id",
      100,
    ),
    kind: "RESUME",
    preferred_tags: [
      ...new Set(
        preferredValue.map((item) => requiredText(item, "Preferred tag", 80)),
      ),
    ],
    excluded_document_ids: [
      ...new Set(
        excludedValue.map((item) => requiredText(item, "Document id", 100)),
      ),
    ],
    prefer_primary: preferPrimary,
  };
}

function challengeInput(value: unknown): ChallengeSessionCreate {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Challenge session input is invalid.");
  }
  const timeLimit = Reflect.get(value, "time_limit_seconds");
  if (
    timeLimit !== undefined &&
    timeLimit !== null &&
    (typeof timeLimit !== "number" || timeLimit < 30 || timeLimit > 28_800)
  ) {
    throw new TypeError("Challenge time limit must be 30 to 28800 seconds.");
  }
  return {
    workflow_id: requiredText(
      Reflect.get(value, "workflow_id"),
      "Workflow id",
      100,
    ),
    browser_session_id: requiredText(
      Reflect.get(value, "browser_session_id"),
      "Browser session id",
      100,
    ),
    ...(typeof timeLimit === "number" ? { time_limit_seconds: timeLimit } : {}),
  };
}

function challengeAnswer(value: unknown): ChallengeAnswerCommand {
  if (typeof value !== "object" || value === null) {
    throw new TypeError("Challenge answer input is invalid.");
  }
  const answer = Reflect.get(value, "value");
  if (typeof answer !== "string" || answer.length > 100_000) {
    throw new TypeError(
      "Challenge answer must be text up to 100000 characters.",
    );
  }
  return {
    question_id: requiredText(
      Reflect.get(value, "question_id"),
      "Question id",
      100,
    ),
    value: answer,
    source: "USER",
    confidence: 1,
  };
}

export function registerWorkbenchIpc(
  supervisor: BackendSupervisor,
  updates: UpdateManager,
  notifications: DesktopNotificationManager,
): void {
  ipcMain.handle("workbench:get-status", () => supervisor.status);
  ipcMain.handle("workbench:list-workflows", () =>
    supervisor.client.listWorkflows(),
  );
  ipcMain.handle(
    "workbench:list-browser-sessions",
    (_event, value: unknown) => {
      if (value === undefined || value === null) {
        return supervisor.client.listBrowserSessions();
      }
      return supervisor.client.listBrowserSessions(
        requiredText(value, "Workflow id", 100),
      );
    },
  );
  ipcMain.handle("knowledge:get", (_event, value: unknown) =>
    supervisor.client.getCandidateKnowledge(
      requiredText(value, "Profile id", 100),
    ),
  );
  ipcMain.handle(
    "knowledge:import-resume",
    async (_event, value: unknown, metadataValue: unknown) => {
      const profileId = requiredText(value, "Profile id", 100);
      const metadata = documentImportInput(metadataValue);
      const selection = await dialog.showOpenDialog({
        title: "Import candidate resume",
        properties: ["openFile"],
        filters: [
          {
            name: "Candidate documents",
            extensions: ["doc", "docx", "pdf", "rtf", "txt", "md"],
          },
        ],
      });
      const filePath = selection.filePaths[0];
      if (selection.canceled || !filePath) return null;
      return supervisor.client.importResume(profileId, filePath, metadata);
    },
  );
  ipcMain.handle("knowledge:preview-selection", (_event, value: unknown) =>
    supervisor.client.previewDocumentSelection(documentSelectionInput(value)),
  );
  ipcMain.handle(
    "knowledge:approve-selection",
    async (
      event,
      value: unknown,
      versionValue: unknown,
      fingerprintValue: unknown,
    ) => {
      const input = documentSelectionInput(value);
      const documentVersionId = requiredText(
        versionValue,
        "Document version id",
        100,
      );
      const fingerprint = requiredText(
        fingerprintValue,
        "Document recommendation fingerprint",
        64,
      );
      const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
      const options = {
        type: "warning" as const,
        title: "Select this reviewed resume?",
        message:
          "The selected immutable resume version will be attached to this application.",
        detail:
          "The backend will refuse if the application, job requirements, variant evidence, or recommendation fingerprint changed.",
        buttons: ["Cancel", "Select reviewed resume"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      };
      const confirmation = owner
        ? await dialog.showMessageBox(owner, options)
        : await dialog.showMessageBox(options);
      if (confirmation.response !== 1) return null;
      return supervisor.client.approveDocumentSelection(
        input,
        documentVersionId,
        fingerprint,
      );
    },
  );
  ipcMain.handle(
    "knowledge:review-claim",
    (_event, claimIdValue: unknown, approvedValue: unknown) => {
      const claimId = requiredText(claimIdValue, "Claim id", 100);
      if (typeof approvedValue !== "boolean") {
        throw new TypeError("Claim approval must be a boolean.");
      }
      return supervisor.client.reviewCandidateClaim(claimId, approvedValue);
    },
  );
  ipcMain.handle(
    "knowledge:create-answer",
    async (event, profileIdValue: unknown, inputValue: unknown) => {
      const profileId = requiredText(profileIdValue, "Profile id", 100);
      const input = answerLibraryInput(inputValue);
      const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
      const options = {
        type: "warning" as const,
        title: "Save this reviewed answer?",
        message: "This answer may be reused in future applications.",
        detail:
          "Only locked, verified evidence is accepted. You can correct the answer later without changing the underlying profile facts.",
        buttons: ["Cancel", "Save reviewed answer"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      };
      const confirmation = owner
        ? await dialog.showMessageBox(owner, options)
        : await dialog.showMessageBox(options);
      if (confirmation.response !== 1) return null;
      return supervisor.client.createAnswer(profileId, input);
    },
  );
  ipcMain.handle(
    "knowledge:update-answer",
    async (
      event,
      answerIdValue: unknown,
      revisionValue: unknown,
      inputValue: unknown,
    ) => {
      const answerId = requiredText(answerIdValue, "Answer id", 100);
      if (
        typeof revisionValue !== "number" ||
        !Number.isInteger(revisionValue) ||
        revisionValue < 1
      ) {
        throw new TypeError("Expected answer revision is invalid.");
      }
      const input = answerLibraryInput(inputValue);
      const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
      const options = {
        type: "warning" as const,
        title: "Save this reviewed correction?",
        message: `Revision ${revisionValue + 1} will become the reusable answer.`,
        detail:
          "The prior revision remains in encrypted history. A stale edit is refused if another revision was saved first.",
        buttons: ["Cancel", "Save reviewed correction"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      };
      const confirmation = owner
        ? await dialog.showMessageBox(owner, options)
        : await dialog.showMessageBox(options);
      if (confirmation.response !== 1) return null;
      return supervisor.client.updateAnswer(answerId, revisionValue, input);
    },
  );
  ipcMain.handle(
    "knowledge:list-answer-revisions",
    (_event, answerIdValue: unknown) =>
      supervisor.client.listAnswerRevisions(
        requiredText(answerIdValue, "Answer id", 100),
      ),
  );
  ipcMain.handle(
    "knowledge:draft-application-answer",
    (_event, value: unknown) =>
      supervisor.client.draftApplicationAnswer(
        applicationAnswerDraftInput(value),
      ),
  );
  ipcMain.handle(
    "knowledge:list-application-answers",
    (_event, applicationIdValue: unknown) =>
      supervisor.client.listApplicationAnswers(
        requiredText(applicationIdValue, "Application id", 100),
      ),
  );
  ipcMain.handle(
    "knowledge:review-application-answer",
    async (
      event,
      answerIdValue: unknown,
      revisionValue: unknown,
      inputValue: unknown,
    ) => {
      const answerId = requiredText(
        answerIdValue,
        "Application answer id",
        100,
      );
      const revision = expectedRevision(revisionValue);
      const input = applicationAnswerReviewInput(inputValue);
      const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
      const options = {
        type: "warning" as const,
        title: "Save this application answer?",
        message: "The reviewed answer will be stored for this application.",
        detail:
          "This does not submit the answer or add it to the reusable library. Stale revisions are refused.",
        buttons: ["Cancel", "Save reviewed application answer"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      };
      const confirmation = owner
        ? await dialog.showMessageBox(owner, options)
        : await dialog.showMessageBox(options);
      if (confirmation.response !== 1) return null;
      return supervisor.client.reviewApplicationAnswer(
        answerId,
        revision,
        input,
      );
    },
  );
  ipcMain.handle(
    "knowledge:promote-application-answer",
    async (event, answerIdValue: unknown, revisionValue: unknown) => {
      const answerId = requiredText(
        answerIdValue,
        "Application answer id",
        100,
      );
      const revision = expectedRevision(revisionValue);
      const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
      const options = {
        type: "warning" as const,
        title: "Promote this reviewed answer?",
        message: "A new locked reusable answer will be created.",
        detail:
          "The application-specific record remains intact and links to the new encrypted library entry.",
        buttons: ["Cancel", "Promote reviewed answer"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      };
      const confirmation = owner
        ? await dialog.showMessageBox(owner, options)
        : await dialog.showMessageBox(options);
      if (confirmation.response !== 1) return null;
      return supervisor.client.promoteApplicationAnswer(answerId, revision);
    },
  );
  ipcMain.handle("knowledge:preview-field-binding", (_event, value: unknown) =>
    supervisor.client.previewApplicationFieldBinding(
      applicationFieldBindingInput(value),
    ),
  );
  ipcMain.handle(
    "knowledge:approve-field-binding",
    async (
      event,
      value: unknown,
      revisionValue: unknown,
      fingerprintValue: unknown,
      permissionValue: unknown,
    ) => {
      const input = applicationFieldBindingInput(value);
      const revision = expectedRevision(revisionValue);
      const fingerprint = requiredText(
        fingerprintValue,
        "Field-binding review fingerprint",
        64,
      );
      const permission = requiredText(
        permissionValue,
        "Field automation permission",
        40,
      );
      if (!new Set(["REVIEW_REQUIRED", "AUTOFILL_ALLOWED"]).has(permission)) {
        throw new TypeError("Field automation permission is invalid.");
      }
      const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
      const options = {
        type: "warning" as const,
        title: "Approve this observed field binding?",
        message: `${input.observed_field.label} will map to the reviewed application answer.`,
        detail:
          "The backend will refuse stale answers, changed observations, incompatible controls, and unattended legal/signature fields.",
        buttons: ["Cancel", "Approve exact field binding"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      };
      const confirmation = owner
        ? await dialog.showMessageBox(owner, options)
        : await dialog.showMessageBox(options);
      if (confirmation.response !== 1) return null;
      return supervisor.client.approveApplicationFieldBinding(
        input,
        revision,
        fingerprint,
        permission as Exclude<FieldAutomationPermission, "PROHIBITED">,
      );
    },
  );
  ipcMain.handle(
    "knowledge:list-field-bindings",
    (_event, applicationIdValue: unknown) =>
      supervisor.client.listApplicationFieldBindings(
        requiredText(applicationIdValue, "Application id", 100),
      ),
  );
  ipcMain.handle(
    "portals:execute-application-field",
    async (
      event,
      runIdValue: unknown,
      bindingIdValue: unknown,
      fingerprintValue: unknown,
    ) => {
      const runId = requiredText(runIdValue, "Supervised portal run id", 100);
      const bindingId = requiredText(bindingIdValue, "Field binding id", 100);
      const fingerprint = requiredText(
        fingerprintValue,
        "Reviewed page fingerprint",
        200,
      );
      const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
      const options = {
        type: "warning" as const,
        title: "Populate this exact approved field?",
        message:
          "One reviewed answer will be entered into the currently observed field.",
        detail:
          "The backend will reject changed pages, answers, controls, legal attestations, uploads, signatures, custom widgets, and all final-submit actions.",
        buttons: ["Cancel", "Populate exact approved field"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      };
      const confirmation = owner
        ? await dialog.showMessageBox(owner, options)
        : await dialog.showMessageBox(options);
      if (confirmation.response !== 1) return null;
      return supervisor.client.executeApplicationField(
        runId,
        bindingId,
        fingerprint,
      );
    },
  );
  ipcMain.handle(
    "portals:list-application-field-executions",
    (_event, applicationIdValue: unknown) =>
      supervisor.client.listApplicationFieldExecutions(
        requiredText(applicationIdValue, "Application id", 100),
      ),
  );
  ipcMain.handle(
    "portals:review-application-field-coverage",
    (_event, runIdValue: unknown, applicationIdValue: unknown) =>
      supervisor.client.reviewApplicationFieldCoverage(
        requiredText(runIdValue, "Supervised portal run id", 100),
        requiredText(applicationIdValue, "Application id", 100),
      ),
  );
  ipcMain.handle("knowledge:preview-tailored", (_event, value: unknown) =>
    supervisor.client.previewTailoredDocument(tailoredDocumentInput(value)),
  );
  ipcMain.handle(
    "knowledge:generate-tailored",
    async (event, value: unknown, fingerprintValue: unknown) => {
      const input = tailoredDocumentInput(value);
      const fingerprint = requiredText(
        fingerprintValue,
        "Tailored document review fingerprint",
        64,
      );
      const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
      const options = {
        type: "warning" as const,
        title: "Generate this exact tailored document?",
        message: `${input.kind === "RESUME" ? "Resume" : "Cover letter"} evidence is locked to the reviewed preview.`,
        detail:
          "The backend will refuse if the job requirements, selected claims, content, or review fingerprint changed.",
        buttons: ["Cancel", "Generate reviewed document"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      };
      const confirmation = owner
        ? await dialog.showMessageBox(owner, options)
        : await dialog.showMessageBox(options);
      if (confirmation.response !== 1) return null;
      const generated = await supervisor.client.generateTailoredDocument(
        input,
        fingerprint,
      );
      const extension = generated.version.file_name.endsWith(".pdf")
        ? "pdf"
        : "docx";
      const target = await dialog.showSaveDialog({
        title: "Save generated application document",
        defaultPath: generated.version.file_name,
        filters: [
          {
            name: extension === "pdf" ? "PDF document" : "Word document",
            extensions: [extension],
          },
        ],
        properties: ["createDirectory", "showOverwriteConfirmation"],
      });
      if (!target.canceled && target.filePath) {
        const data = await supervisor.client.getDocumentContent(
          generated.version.id,
        );
        await writeFile(target.filePath, data, { flag: "w", mode: 0o600 });
      }
      return generated;
    },
  );
  ipcMain.handle("workbench:create-candidate", (_event, value: unknown) =>
    supervisor.client.createCandidate(candidateInput(value)),
  );
  ipcMain.handle("workbench:start-mock", (_event, value: unknown) =>
    supervisor.client.startMockWorkflow(mockWorkflowInput(value)),
  );
  ipcMain.handle("portals:list-runs", () => supervisor.client.listPortalRuns());
  ipcMain.handle("portals:list-catalog", () =>
    supervisor.client.listPortalCatalog(),
  );
  ipcMain.handle("portals:list-supervised", () =>
    supervisor.client.listSupervisedPortalRuns(),
  );
  ipcMain.handle("portals:start-supervised", (_event, value: unknown) =>
    supervisor.client.startSupervisedPortal(supervisedPortalInput(value)),
  );
  ipcMain.handle(
    "portals:capture-supervised",
    (_event, runIdValue: unknown, fingerprintValue: unknown) =>
      supervisor.client.captureSupervisedPortal(
        requiredText(runIdValue, "Supervised portal run id", 100),
        requiredText(fingerprintValue, "Page fingerprint", 200),
      ),
  );
  ipcMain.handle(
    "portals:submit-supervised",
    async (event, runIdValue: unknown, fingerprintValue: unknown) => {
      const runId = requiredText(runIdValue, "Supervised portal run id", 100);
      const fingerprint = requiredText(
        fingerprintValue,
        "Review fingerprint",
        200,
      );
      const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
      const options = {
        type: "warning" as const,
        title: "Submit this exact application?",
        message: "This will activate the one reviewed final-submit control.",
        detail:
          "Job Apply Pro will refuse if the page fingerprint changed, the control is ambiguous, or local submission policy is disabled.",
        buttons: ["Cancel", "Submit exact application"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      };
      const confirmation = owner
        ? await dialog.showMessageBox(owner, options)
        : await dialog.showMessageBox(options);
      if (confirmation.response !== 1) return null;
      return supervisor.client.submitSupervisedPortal(runId, fingerprint);
    },
  );
  ipcMain.handle("portals:stop-supervised", (_event, runIdValue: unknown) =>
    supervisor.client.stopSupervisedPortal(
      requiredText(runIdValue, "Supervised portal run id", 100),
    ),
  );
  ipcMain.handle("challenges:list", (_event, workflowIdValue: unknown) =>
    workflowIdValue === undefined || workflowIdValue === null
      ? supervisor.client.listChallengeSessions()
      : supervisor.client.listChallengeSessions(
          requiredText(workflowIdValue, "Workflow id", 100),
        ),
  );
  ipcMain.handle("communications:integrations", () =>
    supervisor.client.listIntegrationHealth(),
  );
  ipcMain.handle("communications:configuration", () =>
    supervisor.client.getProviderConfigurationStatus(),
  );
  ipcMain.handle("communications:configuration-import", async (event) => {
    const selection = await dialog.showOpenDialog({
      title: "Import provider configuration",
      properties: ["openFile"],
      filters: [{ name: "JSON configuration", extensions: ["json"] }],
    });
    const filePath = selection.filePaths[0];
    if (selection.canceled || !filePath) return null;
    const configurationJson = await readProviderConfigurationFile(filePath);
    const preview =
      await supervisor.client.validateProviderConfiguration(configurationJson);
    const providers = preview.providers
      .map(
        (provider) =>
          `${provider.provider.replaceAll("_", " ")}: ${provider.requested_scopes.length} scopes, ${provider.write_enabled ? "read/write" : "read-only"}`,
      )
      .join("\n");
    const automaticPolicy = preview.automatic_categories.length
      ? `Automatic categories: ${preview.automatic_categories.join(", ")}`
      : "Automatic categories: none";
    const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
    const options = {
      type: "warning" as const,
      title: "Import this provider configuration?",
      message: `Review ${preview.providers.length} provider registration${preview.providers.length === 1 ? "" : "s"}.`,
      detail: `${providers}\n${automaticPolicy}\n\nThis replaces the current local registration. Client IDs and policy metadata will be encrypted in the local database. Passwords, access tokens, refresh tokens, and client secrets are rejected. Importing does not authorize any account.`,
      buttons: ["Cancel", "Import encrypted configuration"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    };
    const confirmation = owner
      ? await dialog.showMessageBox(owner, options)
      : await dialog.showMessageBox(options);
    if (confirmation.response !== 1) return null;
    return supervisor.client.importProviderConfiguration(configurationJson);
  });
  ipcMain.handle("communications:configuration-clear", async (event) => {
    const current = await supervisor.client.getProviderConfigurationStatus();
    if (current.source === "NOT_CONFIGURED") return current;
    if (current.source === "ENVIRONMENT") {
      throw new TypeError(
        "Provider configuration is managed by the process environment.",
      );
    }
    const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
    const options = {
      type: "warning" as const,
      title: "Clear provider configuration?",
      message:
        "Provider connections will be disabled after configuration is cleared.",
      detail:
        "Encrypted OAuth tokens are retained so you can revoke each provider separately before clearing. Clearing does not revoke consent at Google or Microsoft.",
      buttons: ["Cancel", "Clear configuration"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    };
    const confirmation = owner
      ? await dialog.showMessageBox(owner, options)
      : await dialog.showMessageBox(options);
    if (confirmation.response !== 1) return null;
    return supervisor.client.clearProviderConfiguration();
  });
  ipcMain.handle(
    "communications:oauth-start",
    async (_event, providerValue: unknown) => {
      const authorization = await supervisor.client.startProviderAuthorization(
        integrationProvider(providerValue),
      );
      const authorizationUrl = new URL(authorization.authorization_url);
      if (
        authorizationUrl.protocol !== "https:" ||
        !["accounts.google.com", "login.microsoftonline.com"].includes(
          authorizationUrl.hostname,
        )
      ) {
        throw new TypeError("Provider authorization URL is not allowlisted.");
      }
      await shell.openExternal(authorizationUrl.toString());
      return authorization;
    },
  );
  ipcMain.handle(
    "communications:oauth-revoke",
    (_event, providerValue: unknown) =>
      supervisor.client.revokeProviderAuthorization(
        integrationProvider(providerValue),
      ),
  );
  ipcMain.handle(
    "communications:messages-sync",
    (_event, providerValue: unknown) =>
      supervisor.client.syncProviderMessages(
        integrationProvider(providerValue),
      ),
  );
  ipcMain.handle(
    "communications:calendar-sync",
    (_event, providerValue: unknown) =>
      supervisor.client.syncProviderCalendar(
        integrationProvider(providerValue),
      ),
  );
  ipcMain.handle("communications:calendar-events", () =>
    supervisor.client.listSyncedCalendarEvents(),
  );
  ipcMain.handle("communications:records", () =>
    supervisor.client.listCommunicationRecords(),
  );
  ipcMain.handle("communications:daily-summary", () =>
    supervisor.client.getDailyCommunicationSummary(),
  );
  ipcMain.handle("notifications:status", () => notifications.status);
  ipcMain.handle("notifications:refresh", () => notifications.refresh());
  ipcMain.handle(
    "notifications:set-native-enabled",
    (_event, enabledValue: unknown) => {
      if (typeof enabledValue !== "boolean") {
        throw new TypeError("Notification preference must be a boolean.");
      }
      return notifications.setNativeEnabled(enabledValue);
    },
  );
  ipcMain.handle("operations:dashboard", () =>
    supervisor.client.getOperationsDashboard(),
  );
  ipcMain.handle("operations:backups", () => supervisor.client.listBackups());
  ipcMain.handle("operations:backup-schedules", () =>
    supervisor.client.listBackupSchedules(),
  );
  ipcMain.handle("operations:create-backup", (_event, labelValue: unknown) =>
    supervisor.client.createBackup(
      requiredText(labelValue, "Backup label", 200),
    ),
  );
  ipcMain.handle(
    "operations:create-backup-schedule",
    (_event, labelValue: unknown, intervalValue: unknown) => {
      if (
        typeof intervalValue !== "number" ||
        !Number.isInteger(intervalValue) ||
        intervalValue < 1 ||
        intervalValue > 720
      ) {
        throw new TypeError("Backup interval must be 1 to 720 whole hours.");
      }
      return supervisor.client.createBackupSchedule(
        requiredText(labelValue, "Backup schedule label", 200),
        intervalValue,
      );
    },
  );
  ipcMain.handle("operations:verify-backup", (_event, backupIdValue: unknown) =>
    supervisor.client.verifyBackup(
      requiredText(backupIdValue, "Backup id", 100),
    ),
  );
  ipcMain.handle("operations:stage-restore", (_event, backupIdValue: unknown) =>
    supervisor.client.stageRestore(
      requiredText(backupIdValue, "Backup id", 100),
    ),
  );
  ipcMain.handle(
    "operations:apply-restore",
    async (event, planIdValue: unknown, fingerprintValue: unknown) => {
      const planId = requiredText(planIdValue, "Restore plan id", 100);
      const fingerprint = requiredText(
        fingerprintValue,
        "Restore fingerprint",
        64,
      );
      if (!/^[a-f0-9]{64}$/i.test(fingerprint)) {
        throw new TypeError("Restore fingerprint must be a SHA-256 value.");
      }
      const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
      const options = {
        type: "warning" as const,
        title: "Apply verified offline restore?",
        message:
          "Job Apply Pro will stop its local backend and replace the selected data.",
        detail:
          "The current database is retained as a .pre-restore recovery file. The app restarts the backend after the exact reviewed fingerprint is applied.",
        buttons: ["Cancel", "Apply verified restore"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      };
      const confirmation = owner
        ? await dialog.showMessageBox(owner, options)
        : await dialog.showMessageBox(options);
      if (confirmation.response !== 1) return false;
      await supervisor.applyOfflineRestore(planId, fingerprint);
      return true;
    },
  );
  ipcMain.handle("operations:help", () => supervisor.client.listHelpTopics());
  ipcMain.handle("operations:export-diagnostics", async () => {
    const diagnostics = await supervisor.client.getSupportDiagnostics();
    const target = await dialog.showSaveDialog({
      title: "Export redacted Job Apply Pro diagnostics",
      defaultPath: `job-apply-pro-diagnostics-${new Date().toISOString().slice(0, 10)}.json`,
      filters: [{ name: "Redacted diagnostic package", extensions: ["json"] }],
      properties: ["createDirectory", "showOverwriteConfirmation"],
    });
    if (target.canceled || !target.filePath) return null;
    const payload = {
      desktop: {
        application_version: app.getVersion(),
        operating_system: platform(),
        operating_system_release: release(),
        architecture: arch(),
        electron_version: process.versions.electron,
        chrome_version: process.versions.chrome,
        node_version: process.versions.node,
      },
      support: diagnostics,
    };
    await writeFile(target.filePath, `${JSON.stringify(payload, null, 2)}\n`, {
      encoding: "utf8",
      flag: "w",
      mode: 0o600,
    });
    return target.filePath;
  });
  ipcMain.handle("updates:status", () => updates.status);
  ipcMain.handle("updates:check", () => updates.check());
  ipcMain.handle("updates:download", () => updates.download());
  ipcMain.handle("updates:install", () => updates.install());
  ipcMain.handle("challenges:detect", (_event, value: unknown) =>
    supervisor.client.detectChallenge(challengeInput(value)),
  );
  ipcMain.handle("challenges:suggestions", (_event, sessionIdValue: unknown) =>
    supervisor.client.getChallengeSuggestions(
      requiredText(sessionIdValue, "Challenge session id", 100),
    ),
  );
  ipcMain.handle("challenges:model-routes", (_event, sessionIdValue: unknown) =>
    supervisor.client.getChallengeModelRoutes(
      requiredText(sessionIdValue, "Challenge session id", 100),
    ),
  );
  ipcMain.handle("challenges:refresh", (_event, sessionIdValue: unknown) =>
    supervisor.client.refreshChallenge(
      requiredText(sessionIdValue, "Challenge session id", 100),
    ),
  );
  ipcMain.handle(
    "challenges:answer",
    (_event, sessionIdValue: unknown, answerValue: unknown) =>
      supervisor.client.answerChallenge(
        requiredText(sessionIdValue, "Challenge session id", 100),
        challengeAnswer(answerValue),
      ),
  );
  ipcMain.handle(
    "challenges:complete",
    (_event, sessionIdValue: unknown, fingerprintValue: unknown) =>
      supervisor.client.completeChallenge(
        requiredText(sessionIdValue, "Challenge session id", 100),
        requiredText(fingerprintValue, "Review fingerprint", 200),
      ),
  );
  ipcMain.handle(
    "challenges:intervention-complete",
    (_event, sessionIdValue: unknown, fingerprintValue: unknown) =>
      supervisor.client.completeChallengeIntervention(
        requiredText(sessionIdValue, "Challenge session id", 100),
        requiredText(fingerprintValue, "Prior fingerprint", 200),
      ),
  );
  ipcMain.handle("portals:prepare-reference", (_event, value: unknown) =>
    supervisor.client.prepareReferencePortal(referencePortalInput(value)),
  );
  ipcMain.handle(
    "portals:confirm-reference",
    (_event, runIdValue: unknown, fingerprintValue: unknown) =>
      supervisor.client.confirmReferencePortal(
        requiredText(runIdValue, "Portal run id", 100),
        requiredText(fingerprintValue, "Review fingerprint", 200),
      ),
  );
  ipcMain.handle(
    "workbench:control",
    (_event, workflowIdValue: unknown, actionValue: unknown) => {
      const workflowId = requiredText(workflowIdValue, "Workflow id", 100);
      if (
        typeof actionValue !== "string" ||
        !actions.has(actionValue as WorkflowControlAction)
      ) {
        throw new TypeError("Workflow control action is invalid.");
      }
      return supervisor.client.controlWorkflow(
        workflowId,
        actionValue as WorkflowControlAction,
      );
    },
  );
}
