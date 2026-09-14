import type { IpcMainInvokeEvent } from "electron";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CalendarCreateFields,
  CalendarMutationCreate,
  CalendarMutationPlan,
  CommunicationMutationAudit,
  IntegrationHealth,
  ProviderConfigurationStatus,
} from "@job-apply-pro/contracts";

import { BackendClient } from "./backend-client.js";
import {
  registerCalendarEventIpc,
  validateCalendarMutationCreate,
  validateCalendarMutationPlan,
} from "./calendar-event-ipc.js";

type Handler = (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown;
const { handlers, showMessageBox, fromWebContents } = vi.hoisted(() => ({
  handlers: new Map<string, Handler>(),
  showMessageBox: vi.fn(),
  fromWebContents: vi.fn(),
}));
vi.mock("electron", () => ({
  ipcMain: {
    handle: (channel: string, listener: Handler) =>
      handlers.set(channel, listener),
  },
  dialog: { showMessageBox },
  BrowserWindow: { fromWebContents },
}));

const event: CalendarCreateFields = {
  title: "Interview with Example Co",
  start_at: "2026-10-15T15:00:00.000Z",
  end_at: "2026-10-15T16:00:00.000Z",
  time_zone: "America/Chicago",
  attendees: [],
  conferencing_url: null,
  location: "Conference room 3",
  attendee_notification_policy: "NONE",
  reminder_policy: "NONE",
  visibility_policy: "PRIVATE",
  availability_policy: "BUSY",
};
const create: CalendarMutationCreate = {
  provider: "GOOGLE_CALENDAR",
  workflow_id: "workflow-1",
  event: { ...event },
};
const plan: CalendarMutationPlan = {
  id: "calendar-plan-1",
  provider: create.provider,
  workflow_id: create.workflow_id ?? null,
  event: { ...event },
  prior_event: null,
  kind: "CREATE_CALENDAR_EVENT",
  policy_version: "calendar-attempt-v1",
  wire_contract_version: "calendar-create-wire-v1",
  account_key: "a".repeat(64),
  account_label: "candidate@example.invalid",
  calendar_target: "PRIMARY",
  id_assignment: "PROVIDER_NATIVE_DEDUPLICATED",
  provider_dedupe_policy: "NATIVE_ATTEMPT_KEY_V1",
  fingerprint: "b".repeat(64),
  created_at: "2026-09-13T12:00:00.000Z",
};
const accepted: CommunicationMutationAudit = {
  id: "audit-1",
  kind: "CREATE_CALENDAR_EVENT",
  provider: plan.provider,
  resource_id: plan.id,
  idempotency_key: "00000000-0000-4000-8000-000000000001",
  fingerprint: plan.fingerprint,
  status: "CONFIRMED",
  confirmed_by: "desktop-user",
  provider_resource_id: "provider-event-1",
  error_code: null,
  occurred_at: "2026-09-13T12:01:00.000Z",
};
const health: IntegrationHealth[] = [
  {
    provider: plan.provider,
    status: "CONNECTED",
    message: "Provider adapter is connected",
    read_enabled: true,
    write_enabled: true,
    credential_reference: "calendar-credential-1",
    granted_scopes: [
      "https://www.googleapis.com/auth/calendar.readonly",
      "https://www.googleapis.com/auth/calendar.events",
    ],
    account_hint: plan.account_label,
  },
];
const configuration: ProviderConfigurationStatus = {
  source: "ENCRYPTED_DATABASE",
  providers: [
    {
      provider: plan.provider,
      oauth_configured: true,
      requested_scopes: [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
      ],
      read_enabled: true,
      write_enabled: true,
    },
  ],
  automatic_categories: [],
  updated_at: "2026-09-13T10:00:00.000Z",
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("calendar backend-client fixed routes", () => {
  const fetchMock = vi.fn<typeof fetch>();
  let client: BackendClient;

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockImplementation(async () => Response.json(plan));
    vi.stubGlobal("fetch", fetchMock);
    client = new BackendClient("http://127.0.0.1:8765", "test-token");
  });

  it("uses fixed authenticated create, exact-plan, and execute routes", async () => {
    const confirmation = {
      fingerprint: plan.fingerprint,
      idempotency_key: "attempt-key-123",
      confirmed_by: "desktop-user" as const,
    };
    await client.createCalendarPlan(create);
    await client.getCalendarPlan("plan/with?untrusted#segments");
    await client.executeCalendarPlan(plan.id, confirmation);
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "http://127.0.0.1:8765/communications/calendar/plans",
      "http://127.0.0.1:8765/communications/calendar/plans/plan%2Fwith%3Funtrusted%23segments",
      "http://127.0.0.1:8765/communications/calendar/plans/calendar-plan-1/execute",
    ]);
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBe(JSON.stringify(create));
    expect(fetchMock.mock.calls[2]?.[1]?.body).toBe(
      JSON.stringify(confirmation),
    );
    for (const [, options] of fetchMock.mock.calls) {
      expect(options?.headers).toMatchObject({
        "X-Job-Apply-Pro-Token": "test-token",
      });
    }
  });
});

describe("calendar IPC native approval boundary", () => {
  const client = {
    createCalendarPlan: vi.fn<BackendClient["createCalendarPlan"]>(),
    getCalendarPlan: vi.fn<BackendClient["getCalendarPlan"]>(),
    executeCalendarPlan: vi.fn<BackendClient["executeCalendarPlan"]>(),
    getProviderConfigurationStatus:
      vi.fn<BackendClient["getProviderConfigurationStatus"]>(),
    listCommunicationAudits: vi.fn<BackendClient["listCommunicationAudits"]>(),
    listIntegrationHealth: vi.fn<BackendClient["listIntegrationHealth"]>(),
  };

  async function invoke(channel: string, ...args: unknown[]) {
    return handlers.get(channel)!(
      { sender: {} } as IpcMainInvokeEvent,
      ...args,
    );
  }

  beforeEach(() => {
    handlers.clear();
    vi.resetAllMocks();
    client.createCalendarPlan.mockResolvedValue(plan);
    client.getCalendarPlan.mockResolvedValue(plan);
    client.executeCalendarPlan.mockResolvedValue(accepted);
    client.getProviderConfigurationStatus.mockResolvedValue(configuration);
    client.listCommunicationAudits.mockResolvedValue([]);
    client.listIntegrationHealth.mockResolvedValue(health);
    showMessageBox.mockResolvedValue({ response: 1 });
    fromWebContents.mockReturnValue(undefined);
    registerCalendarEventIpc(client);
  });

  it("registers only review-plan and native-create channels", () => {
    expect([...handlers.keys()]).toEqual([
      "communications:calendar-plan-create",
      "communications:calendar-plan-review-create",
    ]);
  });

  it("prepares only a configured, connected, account-bound write plan", async () => {
    await expect(
      invoke("communications:calendar-plan-create", create),
    ).resolves.toEqual(plan);
    expect(client.listIntegrationHealth).toHaveBeenCalledTimes(2);
    expect(client.getProviderConfigurationStatus).toHaveBeenCalledTimes(2);
    expect(client.createCalendarPlan).toHaveBeenCalledExactlyOnceWith(create);
    expect(client.executeCalendarPlan).not.toHaveBeenCalled();
  });

  it("rejects concurrent exact plan preparation rather than creating duplicate plans", async () => {
    let release!: (value: CalendarMutationPlan) => void;
    client.createCalendarPlan.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const first = invoke("communications:calendar-plan-create", create);
    await vi.waitFor(() =>
      expect(client.createCalendarPlan).toHaveBeenCalledOnce(),
    );
    await expect(
      invoke("communications:calendar-plan-create", create),
    ).rejects.toThrow(/already being prepared/);
    release(plan);
    await expect(first).resolves.toEqual(plan);
    expect(client.createCalendarPlan).toHaveBeenCalledTimes(1);
  });

  it("loads twice, shows the exact fixed-policy plan, and owns actor and attempt key", async () => {
    await expect(
      invoke(
        "communications:calendar-plan-review-create",
        plan.id,
        plan.fingerprint,
      ),
    ).resolves.toEqual(accepted);
    expect(client.getCalendarPlan).toHaveBeenCalledTimes(2);
    expect(client.listCommunicationAudits).toHaveBeenCalledTimes(2);
    expect(client.listIntegrationHealth).toHaveBeenCalledTimes(2);
    const options = showMessageBox.mock.calls[0]?.[0];
    expect(options).toMatchObject({
      defaultId: 0,
      cancelId: 0,
      buttons: ["Cancel", "Create reviewed event"],
    });
    for (const expected of [
      "CREATE — one admitted provider attempt",
      plan.provider.replaceAll("_", " "),
      plan.account_label!,
      plan.account_key!,
      "PRIMARY",
      JSON.stringify(plan.event.title),
      plan.event.start_at,
      plan.event.end_at,
      JSON.stringify(plan.event.time_zone),
      JSON.stringify(plan.event.location),
      "Attendees: none",
      "Invitation policy: NONE",
      "Reminder policy: NONE",
      "Visibility: PRIVATE",
      "Availability: BUSY",
      plan.policy_version!,
      plan.wire_contract_version!,
      plan.provider_dedupe_policy!,
      plan.fingerprint,
      "does not prove an exact read-back or delivery",
    ]) {
      expect(options.detail).toContain(expected);
    }
    expect(client.executeCalendarPlan).toHaveBeenCalledExactlyOnceWith(
      plan.id,
      {
        fingerprint: plan.fingerprint,
        confirmed_by: "desktop-user",
        idempotency_key: expect.stringMatching(/^[\da-f-]{36}$/),
      },
    );
    await expect(
      invoke(
        "communications:calendar-plan-review-create",
        plan.id,
        plan.fingerprint,
      ),
    ).rejects.toThrow(/already/);
    expect(client.executeCalendarPlan).toHaveBeenCalledTimes(1);
  });

  it("rejects directional controls before native review", async () => {
    client.getCalendarPlan.mockResolvedValue({
      ...plan,
      event: { ...event, title: "Interview\u202eCREATE" },
    });
    await expect(
      invoke(
        "communications:calendar-plan-review-create",
        plan.id,
        plan.fingerprint,
      ),
    ).resolves.toEqual({
      outcome: "NOT_DISPATCHED",
      reason: "REVIEW_UNAVAILABLE",
    });
    expect(showMessageBox).not.toHaveBeenCalled();
    expect(client.executeCalendarPlan).not.toHaveBeenCalled();
  });

  it("cancels by default without admitting an attempt and permits a fresh review", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 0 });
    await expect(
      invoke(
        "communications:calendar-plan-review-create",
        plan.id,
        plan.fingerprint,
      ),
    ).resolves.toBeNull();
    expect(client.executeCalendarPlan).not.toHaveBeenCalled();
    await invoke(
      "communications:calendar-plan-review-create",
      plan.id,
      plan.fingerprint,
    );
    expect(showMessageBox).toHaveBeenCalledTimes(2);
    expect(client.executeCalendarPlan).toHaveBeenCalledTimes(1);
  });

  it("blocks a concurrent duplicate click before a second dialog or dispatch", async () => {
    let release!: (value: { response: number }) => void;
    showMessageBox.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const first = invoke(
      "communications:calendar-plan-review-create",
      plan.id,
      plan.fingerprint,
    );
    await vi.waitFor(() => expect(showMessageBox).toHaveBeenCalledOnce());
    await expect(
      invoke(
        "communications:calendar-plan-review-create",
        plan.id,
        plan.fingerprint,
      ),
    ).rejects.toThrow(/already/);
    release({ response: 1 });
    await first;
    expect(showMessageBox).toHaveBeenCalledTimes(1);
    expect(client.executeCalendarPlan).toHaveBeenCalledTimes(1);
  });

  it("fails closed before execute when the exact plan changes during approval", async () => {
    client.getCalendarPlan.mockResolvedValueOnce(plan).mockResolvedValueOnce({
      ...plan,
      event: { ...event, title: "Changed title" },
    });
    await expect(
      invoke(
        "communications:calendar-plan-review-create",
        plan.id,
        plan.fingerprint,
      ),
    ).resolves.toEqual({
      outcome: "NOT_DISPATCHED",
      reason: "REVIEW_UNAVAILABLE",
    });
    expect(showMessageBox).toHaveBeenCalledOnce();
    expect(client.executeCalendarPlan).not.toHaveBeenCalled();
  });

  it("fails closed when the provider account reconnects during approval", async () => {
    client.listIntegrationHealth
      .mockResolvedValueOnce(health)
      .mockResolvedValueOnce([
        {
          ...health[0]!,
          credential_reference: "calendar-credential-2",
        },
      ]);
    await expect(
      invoke(
        "communications:calendar-plan-review-create",
        plan.id,
        plan.fingerprint,
      ),
    ).resolves.toEqual({
      outcome: "NOT_DISPATCHED",
      reason: "REVIEW_UNAVAILABLE",
    });
    expect(showMessageBox).toHaveBeenCalledOnce();
    expect(client.executeCalendarPlan).not.toHaveBeenCalled();
  });

  it.each(["PLANNED", "CONFIRMED", "FAILED", "UNCERTAIN"] as const)(
    "returns a durable %s attempt without exposing another review",
    async (status) => {
      const prior = {
        ...accepted,
        status,
        provider_resource_id:
          status === "CONFIRMED" ? accepted.provider_resource_id : null,
        error_code:
          status === "FAILED"
            ? "ProviderCalendarNotAppliedError"
            : status === "UNCERTAIN"
              ? "ProviderCalendarUncertainError"
              : null,
      };
      client.listCommunicationAudits.mockResolvedValue([prior]);
      await expect(
        invoke(
          "communications:calendar-plan-review-create",
          plan.id,
          plan.fingerprint,
        ),
      ).resolves.toEqual(prior);
      expect(showMessageBox).not.toHaveBeenCalled();
      expect(client.executeCalendarPlan).not.toHaveBeenCalled();
      await expect(
        invoke(
          "communications:calendar-plan-review-create",
          plan.id,
          plan.fingerprint,
        ),
      ).rejects.toThrow(/already/);
    },
  );

  it("treats a lost execute response as unresolved and never dispatches again", async () => {
    client.executeCalendarPlan.mockRejectedValueOnce(
      new Error("private provider response"),
    );
    await expect(
      invoke(
        "communications:calendar-plan-review-create",
        plan.id,
        plan.fingerprint,
      ),
    ).rejects.toThrow(/outcome is unresolved/);
    await expect(
      invoke(
        "communications:calendar-plan-review-create",
        plan.id,
        plan.fingerprint,
      ),
    ).rejects.toThrow(/already/);
    expect(client.executeCalendarPlan).toHaveBeenCalledTimes(1);
  });

  it.each([
    null,
    [],
    {},
    { ...create, provider: "GMAIL" },
    { ...create, prior_event: null },
    { ...create, confirmed_by: "renderer" },
    { ...create, idempotency_key: "renderer-key" },
    { ...create, event: { ...event, attendees: ["guest@example.invalid"] } },
    {
      ...create,
      event: { ...event, attendee_notification_policy: "ALL" },
    },
    { ...create, event: { ...event, reminder_policy: "DEFAULT" } },
    { ...create, event: { ...event, visibility_policy: "PUBLIC" } },
    { ...create, event: { ...event, availability_policy: "FREE" } },
    { ...create, event: { ...event, conferencing_url: "https://meet.test" } },
    { ...create, event: { ...event, title: "Bad\nTitle" } },
    { ...create, event: { ...event, title: "Interview\u061ccreate" } },
    { ...create, event: { ...event, location: "Room\ufeff3" } },
    { ...create, event: { ...event, end_at: event.start_at } },
    { ...create, workflow_id: "../workflow" },
  ])(
    "rejects malformed or expanded plan input before backend dispatch (%#)",
    async (value) => {
      expect(() => validateCalendarMutationCreate(value)).toThrow(TypeError);
      await expect(
        invoke("communications:calendar-plan-create", value),
      ).rejects.toThrow(TypeError);
      expect(client.listIntegrationHealth).not.toHaveBeenCalled();
      expect(client.createCalendarPlan).not.toHaveBeenCalled();
    },
  );

  it("keeps plan creation closed without both configured and granted write scope", async () => {
    client.listIntegrationHealth.mockResolvedValue([
      { ...health[0]!, write_enabled: false },
    ]);
    await expect(
      invoke("communications:calendar-plan-create", create),
    ).rejects.toThrow(/No provider event request was made/);
    expect(client.createCalendarPlan).not.toHaveBeenCalled();
  });

  it.each([
    { prior_event: { provider_event_id: "event-1" } },
    { kind: "UPDATE_CALENDAR_EVENT" },
    { policy_version: null },
    { wire_contract_version: null },
    { account_key: null },
    { account_label: null },
    { calendar_target: null },
    { id_assignment: null },
    { provider_dedupe_policy: null },
    { event: { ...event, attendees: ["guest@example.invalid"] } },
    { event: { ...event, attendee_notification_policy: "ALL" } },
    { event: { ...event, reminder_policy: "DEFAULT" } },
    { event: { ...event, visibility_policy: "PUBLIC" } },
    { event: { ...event, availability_policy: "FREE" } },
    { renderer_override: "unsafe" },
  ])("rejects an ineligible or expanded stored plan (%#)", (change) => {
    expect(() => validateCalendarMutationPlan({ ...plan, ...change })).toThrow(
      TypeError,
    );
  });

  it.each(
    [
      [],
      [plan.id],
      [plan.id, plan.fingerprint, { force: true }],
      ["../plan", plan.fingerprint],
      [plan.id, "0"],
      [plan.id, `${plan.fingerprint}\n`],
    ].map((args) => ({ args })),
  )("rejects invalid review arguments before reads (%#)", async ({ args }) => {
    await expect(
      invoke("communications:calendar-plan-review-create", ...args),
    ).rejects.toThrow(TypeError);
    expect(client.getCalendarPlan).not.toHaveBeenCalled();
    expect(showMessageBox).not.toHaveBeenCalled();
  });
});
