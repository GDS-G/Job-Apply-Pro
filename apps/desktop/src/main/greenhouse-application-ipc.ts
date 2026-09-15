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
  "previewGreenhouseApplicationLaunch" | "startGreenhouseApplicationLaunch"
>;

export function registerGreenhouseApplicationIpc(
  client: GreenhouseApplicationClient,
): void {
  const safe = async <T>(operation: () => Promise<T>): Promise<T> => {
    try {
      return await operation();
    } catch {
      throw new Error(
        "The reviewed Greenhouse launch could not be confirmed. Reload current readiness evidence and review again. No application was submitted.",
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
}
