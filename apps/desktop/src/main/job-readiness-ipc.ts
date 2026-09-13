import { BrowserWindow, dialog, ipcMain } from "electron";

import type { BackendClient } from "./backend-client.js";

function record(
  value: unknown,
  keys: readonly string[],
): Record<string, unknown> {
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
    throw new TypeError("Job readiness input is invalid.");
  return value as Record<string, unknown>;
}

function identifier(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{1,100}$/.test(value))
    throw new TypeError("Job readiness identifier is invalid.");
  return value;
}

function fingerprint(value: unknown): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value))
    throw new TypeError("Job readiness fingerprint is invalid.");
  return value;
}

function list<T>(
  value: unknown,
  validate: (item: unknown) => T,
  max = 100,
): T[] {
  if (!Array.isArray(value) || value.length > max)
    throw new TypeError("Job readiness list is invalid.");
  return value.map(validate);
}

function unique(values: string[]): string[] {
  if (new Set(values).size !== values.length)
    throw new TypeError("Job readiness list contains duplicate identifiers.");
  return values;
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean")
    throw new TypeError("Job readiness choice is invalid.");
  return value;
}

function choice<T extends string>(value: unknown, choices: readonly T[]): T {
  if (typeof value !== "string" || !choices.includes(value as T))
    throw new TypeError("Job readiness choice is invalid.");
  return value as T;
}

function requirements(value: unknown) {
  const input = record(value, [
    "application_id",
    "source_fingerprint",
    "items",
  ]);
  const items = list(input.items, (value) => {
    const item = record(value, ["span_id", "classification"]);
    return {
      span_id: fingerprint(item.span_id),
      classification: choice(item.classification, [
        "MANDATORY",
        "PREFERRED",
        "AMBIGUOUS",
      ] as const),
    };
  });
  unique(items.map((item) => item.span_id));
  return {
    application_id: identifier(input.application_id),
    source_fingerprint: fingerprint(input.source_fingerprint),
    items,
  };
}

function qualification(value: unknown) {
  const input = record(value, [
    "application_id",
    "requirements_review_id",
    "findings",
  ]);
  const findings = list(input.findings, (value) => {
    const item = record(value, ["requirement_id", "status", "claim_ids"]);
    return {
      requirement_id: fingerprint(item.requirement_id),
      status: choice(item.status, [
        "SUPPORTED",
        "CONTRADICTED",
        "UNKNOWN",
      ] as const),
      claim_ids: unique(list(item.claim_ids, identifier, 30)),
    };
  });
  unique(findings.map((item) => item.requirement_id));
  if (
    findings.some((item) =>
      item.status === "UNKNOWN"
        ? item.claim_ids.length !== 0
        : item.claim_ids.length === 0,
    )
  )
    throw new TypeError(
      "Each supported or contradicted finding needs reviewed claim links; unknown findings must have none.",
    );
  return {
    application_id: identifier(input.application_id),
    requirements_review_id: identifier(input.requirements_review_id),
    findings,
  };
}

function resume(value: unknown) {
  const input = record(value, [
    "application_id",
    "kind",
    "preferred_tags",
    "excluded_document_ids",
    "prefer_primary",
  ]);
  return {
    application_id: identifier(input.application_id),
    kind: choice(input.kind, ["RESUME"] as const),
    preferred_tags: list(
      input.preferred_tags,
      (value) => {
        if (
          typeof value !== "string" ||
          !value.trim() ||
          value !== value.trim() ||
          value.length > 100 ||
          [...value].some((character) => {
            const code = character.charCodeAt(0);
            return code < 32 || (code >= 127 && code <= 159);
          })
        )
          throw new TypeError("Resume preference is invalid.");
        return value;
      },
      30,
    ),
    excluded_document_ids: unique(
      list(input.excluded_document_ids, identifier),
    ),
    prefer_primary: boolean(input.prefer_primary),
  };
}

type ReadinessClient = Pick<
  BackendClient,
  | "getJobReadiness"
  | "previewJobRequirements"
  | "approveJobRequirements"
  | "previewJobQualification"
  | "approveJobQualification"
  | "previewJobResume"
  | "approveJobResume"
>;

export function registerJobReadinessIpc(client: ReadinessClient): void {
  const safe = async <T>(operation: () => Promise<T>): Promise<T> => {
    try {
      return await operation();
    } catch {
      throw new Error(
        "The saved job review could not be confirmed. Reload its local evidence and review again. No application was submitted.",
      );
    }
  };
  ipcMain.handle("job-readiness:get", (_event, ...args) => {
    if (args.length !== 1)
      throw new TypeError("Job readiness input is invalid.");
    const id = identifier(args[0]);
    return safe(() => client.getJobReadiness(id));
  });
  ipcMain.handle("job-readiness:requirements-preview", (_event, ...args) => {
    if (args.length !== 1)
      throw new TypeError("Job readiness input is invalid.");
    const input = requirements(args[0]);
    return safe(() => client.previewJobRequirements(input));
  });
  ipcMain.handle("job-readiness:qualification-preview", (_event, ...args) => {
    if (args.length !== 1)
      throw new TypeError("Job readiness input is invalid.");
    const input = qualification(args[0]);
    return safe(() => client.previewJobQualification(input));
  });
  ipcMain.handle("job-readiness:resume-preview", (_event, ...args) => {
    if (args.length !== 1)
      throw new TypeError("Job readiness input is invalid.");
    const input = resume(args[0]);
    return safe(() => client.previewJobResume(input));
  });
  for (const kind of ["requirements", "qualification", "resume"] as const) {
    ipcMain.handle(`job-readiness:${kind}-approve`, async (event, ...args) => {
      if (args.length !== 1)
        throw new TypeError("Job readiness approval is invalid.");
      const value = record(
        args[0],
        kind === "requirements"
          ? ["input", "review_fingerprint"]
          : kind === "qualification"
            ? ["input", "review_fingerprint", "approve_eligibility"]
            : ["input", "review_fingerprint", "document_version_id"],
      );
      const reviewed = fingerprint(value.review_fingerprint);
      const operation =
        kind === "requirements"
          ? (() => {
              const input = requirements(value.input);
              return () =>
                client.approveJobRequirements({
                  ...input,
                  review_fingerprint: reviewed,
                  confirmation_phrase: "APPROVE REVIEWED REQUIREMENTS",
                });
            })()
          : kind === "qualification"
            ? (() => {
                const input = qualification(value.input);
                const approved = boolean(value.approve_eligibility);
                return () =>
                  client.approveJobQualification({
                    ...input,
                    review_fingerprint: reviewed,
                    approve_eligibility: approved,
                    confirmation_phrase: "APPROVE REVIEWED QUALIFICATION",
                  });
              })()
            : (() => {
                const input = resume(value.input);
                const version = identifier(value.document_version_id);
                return () =>
                  client.approveJobResume({
                    ...input,
                    review_fingerprint: reviewed,
                    document_version_id: version,
                    confirmation_phrase: "SELECT REVIEWED DOCUMENT",
                  });
              })();
      const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
      const options = {
        type: "warning" as const,
        title: `Approve reviewed ${kind}?`,
        message:
          kind === "requirements"
            ? "Save the exact source requirements you reviewed?"
            : kind === "qualification"
              ? "Save your reviewed evidence findings and eligibility decision?"
              : "Select this reviewed immutable resume version?",
        detail: `Application: ${(value.input as Record<string, unknown>).application_id}\nReview fingerprint: ${reviewed}\n${kind === "resume" ? `Immutable resume version: ${value.document_version_id}\n` : kind === "qualification" ? `Approve eligibility to continue: ${value.approve_eligibility ? "Yes" : "No — save assessment only"}\n` : ""}This is a local evidence review, not a hiring prediction or application submission. Changed source, review, or candidate evidence requires a fresh preview.`,
        buttons: ["Cancel", "Approve reviewed choice"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      };
      const result = owner
        ? await dialog.showMessageBox(owner, options)
        : await dialog.showMessageBox(options);
      if (result.response !== 1) return null;
      return safe(operation);
    });
  }
}
