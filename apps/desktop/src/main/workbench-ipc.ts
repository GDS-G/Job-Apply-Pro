import { writeFile } from "node:fs/promises";
import { arch, platform, release } from "node:os";

import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";

import type {
  CandidateProfileCreate,
  ChallengeAnswerCommand,
  ChallengeSessionCreate,
  IntegrationProvider,
  MockWorkflowCreate,
  PortalKind,
  ReferencePortalRunCreate,
  SupervisedPortalRunCreate,
  TailoredDocumentRequest,
  WorkflowControlAction,
} from "@job-apply-pro/contracts";

import type { BackendSupervisor } from "./backend-supervisor.js";
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
  ipcMain.handle("knowledge:import-resume", async (_event, value: unknown) => {
    const profileId = requiredText(value, "Profile id", 100);
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
    return supervisor.client.importResume(profileId, filePath);
  });
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
  ipcMain.handle("communications:records", () =>
    supervisor.client.listCommunicationRecords(),
  );
  ipcMain.handle("communications:daily-summary", () =>
    supervisor.client.getDailyCommunicationSummary(),
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
