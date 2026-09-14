import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CalendarMutationPlan,
  CommunicationMutationAudit,
  IntegrationHealth,
  ProviderConfigurationStatus,
  WorkflowRunSnapshot,
} from "@job-apply-pro/contracts";

import {
  CalendarEventPanel,
  eligibleCalendarWriteProviders,
} from "./CalendarEventPanel";

const provider: IntegrationHealth = {
  provider: "GOOGLE_CALENDAR",
  status: "CONNECTED",
  message: "Provider adapter is connected",
  read_enabled: true,
  write_enabled: true,
  granted_scopes: [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
  ],
  account_hint: "candidate@example.invalid",
};
const configuration: ProviderConfigurationStatus = {
  source: "ENCRYPTED_DATABASE",
  providers: [
    {
      provider: provider.provider,
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
const workflow: WorkflowRunSnapshot = {
  workflow_id: "workflow-1",
  application_id: "application-1",
  profile_id: "profile-1",
  candidate_display_name: "Synthetic candidate",
  employer: "Example employer",
  title: "Software Engineer",
  state: "DISCOVERED",
  progress: 5,
  updated_at: "2026-09-13T09:00:00.000Z",
  events: [],
};
const plan: CalendarMutationPlan = {
  id: "calendar-plan-1",
  provider: "GOOGLE_CALENDAR",
  workflow_id: workflow.workflow_id,
  event: {
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
  },
  prior_event: null,
  kind: "CREATE_CALENDAR_EVENT",
  policy_version: "calendar-attempt-v1",
  wire_contract_version: "calendar-create-wire-v1",
  account_key: "a".repeat(64),
  account_label: provider.account_hint!,
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
  idempotency_key: "desktop-attempt-key",
  fingerprint: plan.fingerprint,
  status: "CONFIRMED",
  confirmed_by: "desktop-user",
  provider_resource_id: "provider-event-1",
  error_code: null,
  occurred_at: "2026-09-13T12:01:00.000Z",
};

function panel(overrides: { providers?: IntegrationHealth[] } = {}) {
  return render(
    <CalendarEventPanel
      backendReady
      providers={overrides.providers ?? [provider]}
      workflows={[workflow]}
    />,
  );
}

function fillEvent() {
  fireEvent.change(screen.getByLabelText("Owning workflow (optional)"), {
    target: { value: workflow.workflow_id },
  });
  fireEvent.change(screen.getByLabelText("Event title"), {
    target: { value: plan.event.title },
  });
  fireEvent.change(screen.getByLabelText("Starts"), {
    target: { value: "2026-10-15T10:00" },
  });
  fireEvent.change(screen.getByLabelText("Ends"), {
    target: { value: "2026-10-15T11:00" },
  });
  fireEvent.change(screen.getByLabelText("Location (optional)"), {
    target: { value: plan.event.location },
  });
}

async function prepare() {
  fillEvent();
  fireEvent.click(
    screen.getByRole("button", { name: "Prepare exact event review" }),
  );
  await screen.findByRole("heading", { name: "Exact saved calendar plan" });
}

describe("calendar event panel", () => {
  const api = window.jobApplyPro.workbench;

  beforeEach(() => {
    vi.spyOn(api, "createCalendarPlan").mockResolvedValue(plan);
    vi.spyOn(api, "reviewAndCreateCalendarEvent").mockResolvedValue(accepted);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("admits UI only for configured and actually granted calendar write scope", () => {
    expect(eligibleCalendarWriteProviders([provider], configuration)).toEqual([
      provider,
    ]);
    for (const unavailable of [
      null,
      { ...configuration, source: "NOT_CONFIGURED" as const },
      {
        ...configuration,
        providers: [{ ...configuration.providers[0]!, write_enabled: false }],
      },
    ]) {
      expect(eligibleCalendarWriteProviders([provider], unavailable)).toEqual(
        [],
      );
    }
    expect(
      eligibleCalendarWriteProviders(
        [{ ...provider, write_enabled: false }],
        configuration,
      ),
    ).toEqual([]);
    expect(
      eligibleCalendarWriteProviders(
        [
          {
            ...provider,
            granted_scopes: [
              "https://www.googleapis.com/auth/calendar.readonly",
            ],
          },
        ],
        configuration,
      ),
    ).toEqual([]);
  });

  it("prepares only a create-only event with no attendees, invitations, or conferencing", async () => {
    panel();
    expect(
      screen.getByText(/does not add attendees, send invitations/i),
    ).toBeInTheDocument();
    fillEvent();
    fireEvent.click(
      screen.getByRole("button", { name: "Prepare exact event review" }),
    );
    await waitFor(() => expect(api.createCalendarPlan).toHaveBeenCalledOnce());
    const input = vi.mocked(api.createCalendarPlan).mock.calls[0]?.[0];
    expect(input).toMatchObject({
      provider: "GOOGLE_CALENDAR",
      workflow_id: workflow.workflow_id,
      event: {
        title: plan.event.title,
        attendees: [],
        conferencing_url: null,
        location: plan.event.location,
        attendee_notification_policy: "NONE",
        reminder_policy: "NONE",
        visibility_policy: "PRIVATE",
        availability_policy: "BUSY",
      },
    });
    expect(input?.event.start_at).toMatch(
      /^2026-10-15T10:00:00[+-]\d{2}:\d{2}$/,
    );
    expect(input?.event.end_at).toMatch(/^2026-10-15T11:00:00[+-]\d{2}:\d{2}$/);
    expect(input?.event.time_zone).toBeTruthy();
    expect(
      await screen.findByText(/Nothing was sent to the provider/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        (_text, element) =>
          element?.tagName === "DD" &&
          element.textContent?.includes(plan.account_label!) === true,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("None — no attendees")).toBeInTheDocument();
    expect(
      screen.getByText("None — provider defaults disabled"),
    ).toBeInTheDocument();
    expect(screen.getByText("PRIVATE")).toBeInTheDocument();
    expect(screen.getByText("BUSY")).toBeInTheDocument();
  });

  it("requires native review and reports provider acceptance without claiming read-back", async () => {
    panel();
    await prepare();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review & create with native approval",
      }),
    );
    await waitFor(() =>
      expect(api.reviewAndCreateCalendarEvent).toHaveBeenCalledExactlyOnceWith(
        plan.id,
        plan.fingerprint,
      ),
    );
    expect(
      await screen.findByText(/provider accepted this creation/i),
    ).toHaveTextContent(/not an exact event read-back/i);
    expect(screen.getByText(/provider event provider-event-1/i)).toBeVisible();
    expect(
      screen.queryByRole("button", {
        name: "Review & create with native approval",
      }),
    ).not.toBeInTheDocument();
  });

  it("allows another native review after cancellation because no attempt was admitted", async () => {
    vi.mocked(api.reviewAndCreateCalendarEvent).mockResolvedValue(null);
    panel();
    await prepare();
    const createButton = screen.getByRole("button", {
      name: "Review & create with native approval",
    });
    fireEvent.click(createButton);
    expect(
      await screen.findByText(/Native approval cancelled/i),
    ).toBeInTheDocument();
    const nextReview = screen.getByRole("button", {
      name: "Review & create with native approval",
    });
    expect(nextReview).not.toBeDisabled();
    fireEvent.click(nextReview);
    await waitFor(() =>
      expect(api.reviewAndCreateCalendarEvent).toHaveBeenCalledTimes(2),
    );
  });

  it.each(["PLANNED", "FAILED", "UNCERTAIN"] as const)(
    "never exposes retry for a claimed %s attempt",
    async (status) => {
      vi.mocked(api.reviewAndCreateCalendarEvent).mockResolvedValue({
        ...accepted,
        status,
        provider_resource_id: null,
      });
      panel();
      await prepare();
      fireEvent.click(
        screen.getByRole("button", {
          name: "Review & create with native approval",
        }),
      );
      await screen.findByText(
        new RegExp(
          status === "PLANNED"
            ? "attempt was admitted"
            : status === "FAILED"
              ? "permanently closed"
              : "outcome is uncertain",
          "i",
        ),
      );
      expect(
        screen.queryByRole("button", {
          name: "Review & create with native approval",
        }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /retry/i }),
      ).not.toBeInTheDocument();
    },
  );

  it("blocks an unresolved IPC result and never exposes private details or retry", async () => {
    vi.mocked(api.reviewAndCreateCalendarEvent).mockRejectedValue(
      new Error("private provider response body"),
    );
    panel();
    await prepare();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review & create with native approval",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Inspect the bound provider calendar/i,
    );
    expect(screen.queryByText(/private provider response body/)).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: "Review & create with native approval",
      }),
    ).not.toBeInTheDocument();
    expect(api.reviewAndCreateCalendarEvent).toHaveBeenCalledTimes(1);
  });

  it("discards a definitely not-dispatched stale review and requires a new plan", async () => {
    vi.mocked(api.reviewAndCreateCalendarEvent).mockResolvedValue({
      outcome: "NOT_DISPATCHED",
      reason: "REVIEW_UNAVAILABLE",
    });
    panel();
    await prepare();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review & create with native approval",
      }),
    );
    expect(
      await screen.findByText(/No provider event request was dispatched/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Exact saved calendar plan" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Prepare exact event review" }),
    ).not.toBeDisabled();
  });

  it("invalidates a prepared plan when the bound connection changes", async () => {
    const view = panel();
    await prepare();
    view.rerender(
      <CalendarEventPanel
        backendReady
        providers={[
          { ...provider, account_hint: "other-candidate@example.invalid" },
        ]}
        workflows={[workflow]}
      />,
    );
    expect(
      await screen.findByText(/account or write capability changed/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Exact saved calendar plan" }),
    ).not.toBeInTheDocument();
    expect(api.reviewAndCreateCalendarEvent).not.toHaveBeenCalled();
  });

  it("keeps a plan blocked if its connection changes during an unresolved native review", async () => {
    let release!: (value: null) => void;
    vi.mocked(api.reviewAndCreateCalendarEvent).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const view = panel();
    await prepare();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review & create with native approval",
      }),
    );
    await waitFor(() =>
      expect(api.reviewAndCreateCalendarEvent).toHaveBeenCalledOnce(),
    );
    view.rerender(
      <CalendarEventPanel
        backendReady
        providers={[
          { ...provider, account_hint: "other-candidate@example.invalid" },
        ]}
        workflows={[workflow]}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /outcome may be unresolved/i,
    );
    expect(
      screen.queryByRole("button", {
        name: "Review & create with native approval",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Prepare exact event review" }),
    ).toBeDisabled();
    release(null);
  });

  it("does not prepare invalid or duplicate-click plans", async () => {
    let release!: (value: CalendarMutationPlan) => void;
    vi.mocked(api.createCalendarPlan).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    panel();
    fillEvent();
    const button = screen.getByRole("button", {
      name: "Prepare exact event review",
    });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(api.createCalendarPlan).toHaveBeenCalledTimes(1);
    release(plan);
    await screen.findByRole("heading", { name: "Exact saved calendar plan" });
  });
});
