import { BrowserWindow, dialog, ipcMain } from "electron";

import type { BackendClient } from "./backend-client.js";

function record(value: unknown): Record<string, unknown> {
  const keys = [
    "application_id",
    "review_fingerprint",
    "profile_name",
    "engine",
  ];
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value)) ||
    Reflect.ownKeys(value).length !== keys.length ||
    Reflect.ownKeys(value).some(
      (key) => typeof key !== "string" || !keys.includes(key),
    )
  )
    throw new TypeError("Greenhouse application launch input is invalid.");
  return value as Record<string, unknown>;
}

function formActionRecord(value: unknown): Record<string, unknown> {
  const keys = [
    "application_id",
    "run_id",
    "action",
    "control_key",
    "form_review_fingerprint",
  ];
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value)) ||
    Reflect.ownKeys(value).length !== keys.length ||
    Reflect.ownKeys(value).some(
      (key) => typeof key !== "string" || !keys.includes(key),
    )
  )
    throw new TypeError("Greenhouse form action input is invalid.");
  return value as Record<string, unknown>;
}

function identifier(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{1,100}$/.test(value))
    throw new TypeError("Greenhouse application identifier is invalid.");
  return value;
}

function fingerprint(value: unknown): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value))
    throw new TypeError("Greenhouse application fingerprint is invalid.");
  return value;
}

function controlKey(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9_.:-]{1,200}$/.test(value))
    throw new TypeError("Greenhouse form control is invalid.");
  return value;
}

function formAction(
  value: unknown,
): "REVIEW_DOCUMENT_UPLOAD" | "REVIEW_NAVIGATION" {
  if (value !== "REVIEW_DOCUMENT_UPLOAD" && value !== "REVIEW_NAVIGATION")
    throw new TypeError("Greenhouse form action is invalid.");
  return value;
}

function engine(value: unknown): "chromium" | "chrome" | "msedge" {
  if (!new Set(["chromium", "chrome", "msedge"]).has(String(value)))
    throw new TypeError("Greenhouse application browser engine is invalid.");
  return value as "chromium" | "chrome" | "msedge";
}

function display(value: string, max = 200): string {
  return [...value]
    .map((character) => {
      const code = character.charCodeAt(0);
      return code < 32 || (code >= 127 && code <= 159) ? " " : character;
    })
    .join("")
    .trim()
    .slice(0, max);
}

type GreenhouseApplicationClient = Pick<
  BackendClient,
  | "previewGreenhouseApplicationLaunch"
  | "startGreenhouseApplicationLaunch"
  | "previewGreenhouseFormAction"
  | "executeGreenhouseFormAction"
>;

export function registerGreenhouseApplicationIpc(
  client: GreenhouseApplicationClient,
): void {
  const safe = async <T>(operation: () => Promise<T>): Promise<T> => {
    try {
      return await operation();
    } catch {
      throw new Error(
        "The reviewed Greenhouse request could not be confirmed. Reload current evidence and review again. No application was submitted.",
      );
    }
  };
  ipcMain.handle("greenhouse-application:preview", (_event, ...args) => {
    if (args.length !== 1)
      throw new TypeError("Greenhouse application preview is invalid.");
    return safe(() =>
      client.previewGreenhouseApplicationLaunch(identifier(args[0])),
    );
  });
  ipcMain.handle("greenhouse-application:start", async (event, ...args) => {
    if (args.length !== 1)
      throw new TypeError("Greenhouse application launch is invalid.");
    const value = record(args[0]);
    const applicationId = identifier(value.application_id);
    const reviewed = fingerprint(value.review_fingerprint);
    const profileName = identifier(value.profile_name);
    if (profileName.length > 80)
      throw new TypeError("Greenhouse application browser profile is invalid.");
    const browserEngine = engine(value.engine);
    const current = await safe(() =>
      client.previewGreenhouseApplicationLaunch(applicationId),
    );
    if (
      current.application_id !== applicationId ||
      current.review_fingerprint !== reviewed
    )
      throw new Error(
        "The reviewed Greenhouse launch changed. Reload current readiness evidence and review again.",
      );
    const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
    const options = {
      type: "warning" as const,
      title: "Open this reviewed Greenhouse application?",
      message: `${display(current.title)} at ${display(current.employer)}`,
      detail: `Application: ${applicationId}\nOrigin: ${display(current.start_origin, 2_000)}\nImmutable resume version: ${display(current.selected_document_version_id)}\nReview fingerprint: ${reviewed}\nThis opens a visible supervised browser. It does not fill, attest, sign, or submit.`,
      buttons: ["Cancel", "Open reviewed application"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    };
    const result = owner
      ? await dialog.showMessageBox(owner, options)
      : await dialog.showMessageBox(options);
    if (result.response !== 1) return null;
    return safe(() =>
      client.startGreenhouseApplicationLaunch({
        application_id: applicationId,
        review_fingerprint: reviewed,
        profile_name: profileName,
        engine: browserEngine,
        confirmation_phrase: "OPEN REVIEWED GREENHOUSE APPLICATION",
      }),
    );
  });
  ipcMain.handle("greenhouse-form-action:execute", async (event, ...args) => {
    if (args.length !== 1)
      throw new TypeError("Greenhouse form action request is invalid.");
    const value = formActionRecord(args[0]);
    const input = {
      application_id: identifier(value.application_id),
      run_id: identifier(value.run_id),
      action: formAction(value.action),
      control_key: controlKey(value.control_key),
      form_review_fingerprint: fingerprint(value.form_review_fingerprint),
    };
    const current = await safe(() => client.previewGreenhouseFormAction(input));
    if (
      current.application_id !== input.application_id ||
      current.run_id !== input.run_id ||
      current.action !== input.action ||
      current.control_key !== input.control_key ||
      current.form_review_fingerprint !== input.form_review_fingerprint ||
      current.policy_version !== "reviewed-greenhouse-form-action/1" ||
      !/^[a-f0-9]{64}$/.test(current.preview_fingerprint)
    )
      throw new Error(
        "The reviewed Greenhouse form action changed. Capture and review the current page again.",
      );
    const upload = current.action === "REVIEW_DOCUMENT_UPLOAD";
    const documentFields = [
      current.selected_document_version_id,
      current.selected_document_file_name,
      current.selected_document_sha256,
    ];
    const uploadDocumentValid =
      typeof current.selected_document_version_id === "string" &&
      current.selected_document_version_id.length >= 1 &&
      current.selected_document_version_id.length <= 100 &&
      typeof current.selected_document_file_name === "string" &&
      current.selected_document_file_name.length >= 1 &&
      current.selected_document_file_name.length <= 300 &&
      !/[\\/]/.test(current.selected_document_file_name) &&
      typeof current.selected_document_sha256 === "string" &&
      /^[a-f0-9]{64}$/.test(current.selected_document_sha256);
    if (
      (upload && !uploadDocumentValid) ||
      (!upload && documentFields.some((value) => value != null))
    )
      throw new Error(
        "The reviewed Greenhouse form action changed. Capture and review the current page again.",
      );
    const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
    const options = {
      type: "warning" as const,
      title: upload
        ? "Upload this exact reviewed document?"
        : "Advance this exact reviewed Greenhouse form?",
      message: `${display(current.control_label)} on ${display(current.stage.toLowerCase())}`,
      detail: upload
        ? `Application: ${input.application_id}\nDocument: ${display(current.selected_document_file_name ?? "Unavailable", 300)}\nImmutable version: ${display(current.selected_document_version_id ?? "Unavailable")}\nSHA-256: ${display(current.selected_document_sha256 ?? "Unavailable", 64)}\nPage: ${display(current.page_fingerprint)}\nForm review: ${input.form_review_fingerprint}\nThe temporary plaintext file is removed after this one reviewed upload. A visible filename is not final-submission proof.`
        : `Application: ${input.application_id}\nCurrent stage: ${display(current.stage)}\nControl: ${display(current.control_label)}\nPage: ${display(current.page_fingerprint)}\nForm review: ${input.form_review_fingerprint}\nThe action must remain on the exact Greenhouse origin and reach a recognized later stage. It cannot submit the application.`,
      buttons: [
        "Cancel",
        upload ? "Upload reviewed document" : "Advance reviewed form",
      ],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    };
    const result = owner
      ? await dialog.showMessageBox(owner, options)
      : await dialog.showMessageBox(options);
    if (result.response !== 1) return null;
    return safe(() =>
      client.executeGreenhouseFormAction({
        ...input,
        preview_fingerprint: current.preview_fingerprint,
        confirmation_phrase: upload
          ? "UPLOAD REVIEWED GREENHOUSE DOCUMENT"
          : "ADVANCE REVIEWED GREENHOUSE FORM",
      }),
    );
  });
}
