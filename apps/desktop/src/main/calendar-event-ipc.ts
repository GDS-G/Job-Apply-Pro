import { randomUUID } from "node:crypto";

import { BrowserWindow, dialog, ipcMain } from "electron";

import type {
  CalendarMutationCreate,
  CalendarMutationPlan,
  CommunicationMutationAudit,
  IntegrationHealth,
  ProviderConfigurationStatus,
} from "@job-apply-pro/contracts";

import type { BackendClient } from "./backend-client.js";

type CalendarProvider = "GOOGLE_CALENDAR" | "OUTLOOK_CALENDAR";
type CalendarAttemptClient = Pick<
  BackendClient,
  | "createCalendarPlan"
  | "executeCalendarPlan"
  | "getCalendarPlan"
  | "getProviderConfigurationStatus"
  | "listCommunicationAudits"
  | "listIntegrationHealth"
>;

const calendarProviders = new Set<CalendarProvider>([
  "GOOGLE_CALENDAR",
  "OUTLOOK_CALENDAR",
]);
const calendarPlanKeys = [
  "id",
  "provider",
  "workflow_id",
  "event",
  "prior_event",
  "kind",
  "policy_version",
  "wire_contract_version",
  "account_key",
  "account_label",
  "calendar_target",
  "id_assignment",
  "provider_dedupe_policy",
  "fingerprint",
  "created_at",
] as const;
const calendarEventKeys = [
  "title",
  "start_at",
  "end_at",
  "time_zone",
  "attendees",
  "conferencing_url",
  "location",
  "attendee_notification_policy",
  "reminder_policy",
  "visibility_policy",
  "availability_policy",
] as const;
const auditKeys = [
  "id",
  "kind",
  "provider",
  "resource_id",
  "idempotency_key",
  "fingerprint",
  "status",
  "confirmed_by",
  "provider_resource_id",
  "error_code",
  "occurred_at",
] as const;

function record(value: unknown, message: string): Record<string, unknown> {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  ) {
    throw new TypeError(message);
  }
  return value as Record<string, unknown>;
}

function exactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
  message: string,
): void {
  const allowed = new Set(keys);
  if (
    Reflect.ownKeys(value).length !== keys.length ||
    Reflect.ownKeys(value).some(
      (key) => typeof key !== "string" || !allowed.has(key),
    )
  ) {
    throw new TypeError(message);
  }
}

function boundedText(
  value: unknown,
  label: string,
  limit: number,
  allowEmpty = false,
): string {
  if (
    typeof value !== "string" ||
    value.length > limit ||
    (!allowEmpty && !value.trim()) ||
    /[\p{C}\u2028\u2029]/u.test(value)
  ) {
    throw new TypeError(`${label} is invalid.`);
  }
  return value;
}

function identifier(value: unknown, label: string): string {
  if (typeof value !== "string" || !/^[a-zA-Z0-9_-]{1,100}$/.test(value)) {
    throw new TypeError(`${label} is invalid.`);
  }
  return value;
}

function fingerprint(value: unknown, label: string): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) {
    throw new TypeError(`${label} is invalid.`);
  }
  return value;
}

function calendarProvider(value: unknown): CalendarProvider {
  if (!calendarProviders.has(value as CalendarProvider)) {
    throw new TypeError("Calendar provider is invalid.");
  }
  return value as CalendarProvider;
}

function timestamp(value: unknown, label: string): string {
  const result = boundedText(value, label, 64);
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/.test(
      result,
    ) ||
    !Number.isFinite(Date.parse(result))
  ) {
    throw new TypeError(`${label} must be an ISO timestamp with a UTC offset.`);
  }
  return result;
}

function timeZone(value: unknown): string {
  const result = boundedText(value, "Calendar time zone", 100);
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: result }).format(new Date(0));
  } catch {
    throw new TypeError("Calendar time zone is invalid.");
  }
  return result;
}

function optionalText(
  value: unknown,
  label: string,
  limit: number,
): string | null {
  return value === null ? null : boundedText(value, label, limit);
}

function accountLabel(value: unknown): string {
  const result = boundedText(value, "Calendar account", 254);
  const match =
    /^([A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*)@([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)$/.exec(
      result,
    );
  if (
    !match ||
    match[1]!.length > 64 ||
    match[2]!.length > 253 ||
    match[2]!
      .split(".")
      .some(
        (part) =>
          part.length < 1 ||
          part.length > 63 ||
          part.startsWith("-") ||
          part.endsWith("-"),
      )
  ) {
    throw new TypeError("Calendar account is invalid.");
  }
  return `${match[1]}@${match[2]!.toLowerCase()}`;
}

function calendarEvent(value: unknown): CalendarMutationCreate["event"] {
  const input = record(value, "Calendar event is invalid.");
  exactKeys(input, calendarEventKeys, "Calendar event fields are invalid.");
  if (!Array.isArray(input.attendees) || input.attendees.length !== 0) {
    throw new TypeError(
      "Calendar attendees are not supported in this release.",
    );
  }
  if (
    input.conferencing_url !== null ||
    input.attendee_notification_policy !== "NONE" ||
    input.reminder_policy !== "NONE" ||
    input.visibility_policy !== "PRIVATE" ||
    input.availability_policy !== "BUSY"
  ) {
    throw new TypeError(
      "Calendar events must use the reviewed no-invites, no-reminders, private, busy policy without conferencing.",
    );
  }
  const startAt = timestamp(input.start_at, "Calendar start");
  const endAt = timestamp(input.end_at, "Calendar end");
  if (Date.parse(endAt) <= Date.parse(startAt)) {
    throw new TypeError("Calendar end must be after its start.");
  }
  return {
    title: boundedText(input.title, "Calendar title", 1_000),
    start_at: startAt,
    end_at: endAt,
    time_zone: timeZone(input.time_zone),
    attendees: [],
    conferencing_url: null,
    location: optionalText(input.location, "Calendar location", 1_000),
    attendee_notification_policy: "NONE",
    reminder_policy: "NONE",
    visibility_policy: "PRIVATE",
    availability_policy: "BUSY",
  };
}

export function validateCalendarMutationCreate(
  value: unknown,
): CalendarMutationCreate {
  const input = record(value, "Calendar plan input is invalid.");
  exactKeys(
    input,
    ["provider", "workflow_id", "event"],
    "Calendar plan fields are invalid.",
  );
  return {
    provider: calendarProvider(input.provider),
    workflow_id:
      input.workflow_id === null
        ? null
        : identifier(input.workflow_id, "Calendar workflow"),
    event: calendarEvent(input.event),
  };
}

export function validateCalendarMutationPlan(
  value: unknown,
): CalendarMutationPlan {
  const plan = record(value, "Calendar plan is invalid.");
  exactKeys(plan, calendarPlanKeys, "Calendar plan fields are invalid.");
  const provider = calendarProvider(plan.provider);
  const workflowId =
    plan.workflow_id === null
      ? null
      : identifier(plan.workflow_id, "Calendar workflow");
  const event = calendarEvent(plan.event);
  if (
    plan.prior_event !== null ||
    plan.kind !== "CREATE_CALENDAR_EVENT" ||
    plan.policy_version !== "calendar-attempt-v1" ||
    plan.wire_contract_version !== "calendar-create-wire-v1" ||
    plan.calendar_target !== "PRIMARY" ||
    plan.id_assignment !== "PROVIDER_NATIVE_DEDUPLICATED" ||
    plan.provider_dedupe_policy !== "NATIVE_ATTEMPT_KEY_V1"
  ) {
    throw new TypeError("Calendar plan is not eligible for reviewed creation.");
  }
  return {
    id: identifier(plan.id, "Calendar plan id"),
    provider,
    workflow_id: workflowId,
    event,
    prior_event: null,
    kind: "CREATE_CALENDAR_EVENT",
    policy_version: "calendar-attempt-v1",
    wire_contract_version: "calendar-create-wire-v1",
    account_key: fingerprint(plan.account_key, "Calendar account binding"),
    account_label: accountLabel(plan.account_label),
    calendar_target: "PRIMARY",
    id_assignment: "PROVIDER_NATIVE_DEDUPLICATED",
    provider_dedupe_policy: "NATIVE_ATTEMPT_KEY_V1",
    fingerprint: fingerprint(plan.fingerprint, "Calendar review fingerprint"),
    created_at: timestamp(plan.created_at, "Calendar plan creation time"),
  };
}

function quoted(value: string): string {
  return JSON.stringify(value).replace(
    /[\u2028-\u202e\u2066-\u2069]/g,
    (character) =>
      `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
}

function planSignature(plan: CalendarMutationPlan): string {
  return JSON.stringify(plan);
}

function reviewDetails(plan: CalendarMutationPlan): string {
  return [
    "Operation: CREATE — one admitted provider attempt",
    `Provider: ${plan.provider.replaceAll("_", " ")}`,
    `Calendar account: ${quoted(plan.account_label!)}`,
    `Account binding SHA-256: ${plan.account_key}`,
    "Calendar target: PRIMARY",
    `Title: ${quoted(plan.event.title)}`,
    `Start: ${plan.event.start_at}`,
    `End: ${plan.event.end_at}`,
    `Time zone: ${quoted(plan.event.time_zone)}`,
    `Location: ${plan.event.location === null || plan.event.location === undefined ? "None" : quoted(plan.event.location)}`,
    "Attendees: none",
    "Invitation policy: NONE — this release does not add attendees or send invitations.",
    "Reminder policy: NONE — provider-default reminders are disabled.",
    "Visibility: PRIVATE",
    "Availability: BUSY",
    "Conferencing: none",
    `Workflow: ${plan.workflow_id ?? "None"}`,
    `Attempt policy: ${plan.policy_version}`,
    `Wire contract: ${plan.wire_contract_version}`,
    `Provider duplicate protection: ${plan.provider_dedupe_policy}`,
    `Review SHA-256: ${plan.fingerprint}`,
    "The provider may accept and create the event, but this action does not prove an exact read-back or delivery. An admitted attempt is never retried from this plan; inspect the provider calendar if its outcome is unresolved.",
  ].join("\n\n");
}

function requiredWriteScope(provider: CalendarProvider): string {
  return provider === "GOOGLE_CALENDAR"
    ? "https://www.googleapis.com/auth/calendar.events"
    : "Calendars.ReadWrite";
}

function capabilitySignature(
  provider: CalendarProvider,
  health: IntegrationHealth[],
  configuration: ProviderConfigurationStatus,
  expectedAccount?: string,
): string {
  if (
    configuration.source !== "ENVIRONMENT" &&
    configuration.source !== "ENCRYPTED_DATABASE"
  ) {
    throw new TypeError("Calendar write configuration is unavailable.");
  }
  const scope = requiredWriteScope(provider);
  const registrations = configuration.providers.filter(
    (item) => item.provider === provider,
  );
  const connections = health.filter((item) => item.provider === provider);
  const registration = registrations[0];
  const connection = connections[0];
  const normalizedAccount =
    typeof connection?.account_hint === "string"
      ? accountLabel(connection.account_hint)
      : null;
  if (
    registrations.length !== 1 ||
    connections.length !== 1 ||
    !registration ||
    !connection ||
    !registration.oauth_configured ||
    !registration.write_enabled ||
    !registration.requested_scopes.includes(scope) ||
    connection.status !== "CONNECTED" ||
    !connection.write_enabled ||
    !connection.granted_scopes.includes(scope) ||
    typeof connection.credential_reference !== "string" ||
    !/^[a-zA-Z0-9._:-]{1,200}$/.test(connection.credential_reference) ||
    normalizedAccount === null ||
    (expectedAccount !== undefined && normalizedAccount !== expectedAccount)
  ) {
    throw new TypeError("Verified calendar write capability is unavailable.");
  }
  return JSON.stringify({
    provider,
    source: configuration.source,
    configuration_updated_at: configuration.updated_at ?? null,
    requested_scopes: [...registration.requested_scopes].sort(),
    credential_reference: connection.credential_reference,
    granted_scopes: [...connection.granted_scopes].sort(),
    account_hint: normalizedAccount,
  });
}

async function currentCapability(
  client: CalendarAttemptClient,
  provider: CalendarProvider,
  expectedAccount?: string,
): Promise<string> {
  const [health, configuration] = await Promise.all([
    client.listIntegrationHealth(),
    client.getProviderConfigurationStatus(),
  ]);
  return capabilitySignature(provider, health, configuration, expectedAccount);
}

function validateCalendarAudit(
  value: unknown,
  plan: CalendarMutationPlan,
): CommunicationMutationAudit {
  const audit = record(value, "Calendar audit is invalid.");
  exactKeys(audit, auditKeys, "Calendar audit fields are invalid.");
  if (
    audit.kind !== "CREATE_CALENDAR_EVENT" ||
    audit.provider !== plan.provider ||
    audit.resource_id !== plan.id ||
    audit.fingerprint !== plan.fingerprint ||
    audit.confirmed_by !== "desktop-user" ||
    !["PLANNED", "CONFIRMED", "FAILED", "UNCERTAIN"].includes(
      audit.status as string,
    ) ||
    (audit.status === "CONFIRMED" &&
      (typeof audit.provider_resource_id !== "string" ||
        !audit.provider_resource_id ||
        audit.error_code !== null)) ||
    (audit.status === "PLANNED" &&
      (audit.provider_resource_id !== null || audit.error_code !== null)) ||
    ((audit.status === "FAILED" || audit.status === "UNCERTAIN") &&
      (audit.provider_resource_id !== null ||
        typeof audit.error_code !== "string" ||
        !audit.error_code)) ||
    (audit.provider_resource_id !== null &&
      (typeof audit.provider_resource_id !== "string" ||
        audit.provider_resource_id.length > 500 ||
        /[^\x21-\x7e]/.test(audit.provider_resource_id))) ||
    (audit.error_code !== null &&
      (typeof audit.error_code !== "string" ||
        !/^[A-Za-z][A-Za-z0-9_.:-]{0,99}$/.test(audit.error_code)))
  ) {
    throw new TypeError("Calendar audit does not match the reviewed plan.");
  }
  identifier(audit.id, "Calendar audit id");
  if (
    typeof audit.idempotency_key !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
      audit.idempotency_key,
    )
  ) {
    throw new TypeError("Calendar attempt key is invalid.");
  }
  timestamp(audit.occurred_at, "Calendar audit time");
  return audit as unknown as CommunicationMutationAudit;
}

function priorCalendarAudit(
  values: CommunicationMutationAudit[],
  plan: CalendarMutationPlan,
  onFound: () => void,
): CommunicationMutationAudit | undefined {
  const matches = values.filter((audit) => audit.resource_id === plan.id);
  if (!matches.length) return undefined;
  onFound();
  if (matches.length !== 1) {
    throw new TypeError("Calendar attempt history is inconsistent.");
  }
  return validateCalendarAudit(matches[0], plan);
}

export function registerCalendarEventIpc(client: CalendarAttemptClient): void {
  const preparing = new Set<string>();
  const attempts = new Map<string, "reviewing" | "dispatched">();

  ipcMain.handle(
    "communications:calendar-plan-create",
    async (_event, ...args: unknown[]) => {
      if (args.length !== 1) {
        throw new TypeError("One calendar plan input is required.");
      }
      const input = validateCalendarMutationCreate(args[0]);
      const inputKey = JSON.stringify(input);
      if (preparing.has(inputKey)) {
        throw new Error("This exact calendar plan is already being prepared.");
      }
      preparing.add(inputKey);
      try {
        const before = await currentCapability(client, input.provider);
        const plan = validateCalendarMutationPlan(
          await client.createCalendarPlan(input),
        );
        if (
          plan.provider !== input.provider ||
          plan.workflow_id !== input.workflow_id ||
          before !==
            (await currentCapability(
              client,
              plan.provider,
              plan.account_label!,
            ))
        ) {
          throw new TypeError("Calendar account changed during preparation.");
        }
        return plan;
      } catch {
        throw new Error(
          "Calendar event could not be prepared for exact review. Refresh the provider connection and try again. No provider event request was made.",
        );
      } finally {
        preparing.delete(inputKey);
      }
    },
  );

  ipcMain.handle(
    "communications:calendar-plan-review-create",
    async (
      event,
      ...args: unknown[]
    ): Promise<
      | CommunicationMutationAudit
      | null
      | { outcome: "NOT_DISPATCHED"; reason: "REVIEW_UNAVAILABLE" }
    > => {
      if (args.length !== 2) {
        throw new TypeError(
          "Calendar plan id and reviewed fingerprint are required.",
        );
      }
      const id = identifier(args[0], "Calendar plan id");
      const reviewed = fingerprint(args[1], "Calendar reviewed fingerprint");
      if (attempts.has(id)) {
        throw new Error(
          "This calendar plan already has a review or admitted attempt; inspect its outcome.",
        );
      }
      attempts.set(id, "reviewing");
      try {
        const plan = validateCalendarMutationPlan(
          await client.getCalendarPlan(id),
        );
        if (plan.id !== id || plan.fingerprint !== reviewed) {
          throw new TypeError("Calendar plan changed; refresh and review.");
        }
        const detail = reviewDetails(plan);
        const signature = planSignature(plan);
        const capability = await currentCapability(
          client,
          plan.provider as CalendarProvider,
          plan.account_label!,
        );
        const prior = priorCalendarAudit(
          await client.listCommunicationAudits(),
          plan,
          () => attempts.set(id, "dispatched"),
        );
        if (prior) return prior;

        const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
        const options = {
          type: "warning" as const,
          title: "Review calendar event creation",
          message: "Create this exact calendar event once?",
          detail,
          buttons: ["Cancel", "Create reviewed event"],
          defaultId: 0,
          cancelId: 0,
          noLink: true,
        };
        const confirmation = owner
          ? await dialog.showMessageBox(owner, options)
          : await dialog.showMessageBox(options);
        if (confirmation.response !== 1) return null;

        const current = validateCalendarMutationPlan(
          await client.getCalendarPlan(id),
        );
        if (
          current.id !== id ||
          current.fingerprint !== reviewed ||
          planSignature(current) !== signature ||
          reviewDetails(current) !== detail ||
          (await currentCapability(
            client,
            current.provider as CalendarProvider,
            current.account_label!,
          )) !== capability
        ) {
          throw new TypeError(
            "Calendar plan or account changed during approval.",
          );
        }
        const raced = priorCalendarAudit(
          await client.listCommunicationAudits(),
          current,
          () => attempts.set(id, "dispatched"),
        );
        if (raced) return raced;

        attempts.set(id, "dispatched");
        const result = await client.executeCalendarPlan(id, {
          fingerprint: reviewed,
          idempotency_key: randomUUID(),
          confirmed_by: "desktop-user",
        });
        return validateCalendarAudit(result, current);
      } catch {
        if (attempts.get(id) === "reviewing") {
          return { outcome: "NOT_DISPATCHED", reason: "REVIEW_UNAVAILABLE" };
        }
        throw new Error(
          "Calendar creation outcome is unresolved. Inspect the bound provider calendar; do not retry this plan or create a duplicate event.",
        );
      } finally {
        if (attempts.get(id) === "reviewing") attempts.delete(id);
      }
    },
  );
}
