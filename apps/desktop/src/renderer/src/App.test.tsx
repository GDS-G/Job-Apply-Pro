import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  PortalRunSnapshot,
  WorkflowControlAction,
  WorkflowRunSnapshot,
} from "@job-apply-pro/contracts";

import { App } from "./App";

const discoveredWorkflow: WorkflowRunSnapshot = {
  workflow_id: "discovery-1",
  application_id: "application-1",
  profile_id: "profile-1",
  candidate_display_name: "Synthetic candidate",
  employer: "Example employer",
  title: "Discovered real job",
  state: "DISCOVERED",
  progress: 5,
  updated_at: "2026-09-15T10:00:00Z",
  events: [],
};

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it.each([undefined, []] as (WorkflowControlAction[] | undefined)[])(
    "denies synthetic controls when the server grants none (%s)",
    async (allowedControls) => {
      const item: WorkflowRunSnapshot = {
        ...discoveredWorkflow,
        ...(allowedControls ? { allowed_controls: allowedControls } : {}),
      };
      vi.spyOn(window.jobApplyPro.workbench, "listWorkflows").mockResolvedValue(
        [item],
      );
      const control = vi.spyOn(window.jobApplyPro.workbench, "controlWorkflow");
      render(<App />);
      await screen.findByText(item.title);
      for (const name of [
        "Advance mock run",
        "Pause",
        "Retry checkpoint",
        "Take over",
        "Stop safely",
      ]) {
        const button = screen.getByRole("button", { name });
        expect(button).toBeDisabled();
        fireEvent.click(button);
      }
      expect(control).not.toHaveBeenCalled();
    },
  );

  it("enables only synthetic controls explicitly granted by the server", async () => {
    const item: WorkflowRunSnapshot = {
      ...discoveredWorkflow,
      workflow_id: "mock-1",
      allowed_controls: ["ADVANCE"],
    };
    vi.spyOn(window.jobApplyPro.workbench, "listWorkflows").mockResolvedValue([
      item,
    ]);
    const control = vi
      .spyOn(window.jobApplyPro.workbench, "controlWorkflow")
      .mockResolvedValue({
        ...item,
        state: "DEDUPLICATED",
        allowed_controls: [],
      });
    render(<App />);
    await screen.findByText(item.title);
    const advance = screen.getByRole("button", { name: "Advance mock run" });
    expect(advance).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Pause" })).toBeDisabled();
    fireEvent.click(advance);
    await waitFor(() =>
      expect(control).toHaveBeenCalledExactlyOnceWith("mock-1", "ADVANCE"),
    );
    await waitFor(() => expect(advance).toBeDisabled());
  });

  it("preserves the separately reviewed reference ATS submission control", async () => {
    const run: PortalRunSnapshot = {
      id: "fixture-run",
      portal: "REFERENCE_ATS",
      capabilities: [],
      workflow_id: discoveredWorkflow.workflow_id,
      application_id: discoveredWorkflow.application_id,
      browser_session_id: "fixture-browser",
      profile_id: discoveredWorkflow.profile_id,
      job_id: "fixture-job",
      state: "READY_TO_SUBMIT",
      portal_origin: "http://127.0.0.1:4173",
      query: "Synthetic",
      deduplicated: true,
      qualification: {
        score: 1,
        threshold: 0.5,
        eligible: true,
        matched_terms: [],
        missing_terms: [],
        evidence_claim_ids: [],
      },
      selected_document_version_id: "fixture-version",
      field_mappings: [],
      review_fingerprint: "a".repeat(64),
      created_at: discoveredWorkflow.updated_at,
      updated_at: discoveredWorkflow.updated_at,
    };
    vi.spyOn(window.jobApplyPro.workbench, "listWorkflows").mockResolvedValue([
      { ...discoveredWorkflow, allowed_controls: [] },
    ]);
    vi.spyOn(window.jobApplyPro.workbench, "listPortalRuns").mockResolvedValue([
      run,
    ]);
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "Confirm fixture submission" }),
    ).not.toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Advance mock run" }),
    ).toBeDisabled();
  });

  it("shows the Workbench safety boundary", () => {
    render(<App />);

    expect(
      screen.getByText("Gemini Processing Budget v0.57.0-alpha.1"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /production submission and provider writes are disabled/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/reference ATS vertical slice/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /challenge framework/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /communication & scheduling/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: /operations, recovery & licensing/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create verified backup/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /stage restore/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /schedule daily/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/application report/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /export diagnostics/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/updates are disabled for development builds/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create encrypted profile/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Template")).toBeInTheDocument();
    expect(screen.getByLabelText("Evidence ranking")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /explainable resume selection/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /choose & import resume/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(/allow external AI processing/i),
    ).not.toBeChecked();
  });

  it("has no serious automated accessibility violations", async () => {
    const { container } = render(<App />);
    const result = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });

    expect(
      result.violations.filter(({ impact }) =>
        ["serious", "critical"].includes(impact ?? ""),
      ),
    ).toEqual([]);
  });

  it("syncs connected provider messages and reports bounded counts", async () => {
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listIntegrationHealth",
    ).mockResolvedValue([
      {
        provider: "GMAIL",
        status: "CONNECTED",
        message: "Provider adapter is connected",
        read_enabled: true,
        write_enabled: false,
        granted_scopes: ["gmail.readonly"],
      },
    ]);
    const sync = vi
      .spyOn(window.jobApplyPro.workbench, "syncProviderMessages")
      .mockResolvedValue({
        provider: "GMAIL",
        fetched_count: 2,
        imported_count: 1,
        duplicate_count: 1,
        record_ids: ["record-1", "record-1"],
        sync_mode: "INCREMENTAL",
        cursor_updated_at: "2026-08-11T23:00:00Z",
      });

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /sync messages/i }),
    );

    expect(sync).toHaveBeenCalledWith("GMAIL");
    expect(
      await screen.findByText(
        /incremental sync fetched 2, imported 1, already present 1/i,
      ),
    ).toBeInTheDocument();
  });

  it("syncs a connected calendar and reports reconciliation counts", async () => {
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listIntegrationHealth",
    ).mockResolvedValue([
      {
        provider: "GOOGLE_CALENDAR",
        status: "CONNECTED",
        message: "Provider adapter is connected",
        read_enabled: true,
        write_enabled: false,
        granted_scopes: ["calendar.readonly"],
      },
    ]);
    const sync = vi
      .spyOn(window.jobApplyPro.workbench, "syncProviderCalendar")
      .mockResolvedValue({
        provider: "GOOGLE_CALENDAR",
        fetched_count: 3,
        stored_count: 3,
        removed_count: 1,
        window_start: "2026-08-10T00:00:00Z",
        window_end: "2026-10-10T00:00:00Z",
        synced_at: "2026-08-11T00:00:00Z",
      });

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /sync calendar/i }),
    );

    expect(sync).toHaveBeenCalledWith("GOOGLE_CALENDAR");
    expect(
      await screen.findByText(/fetched 3, stored 3, removed 1 stale events/i),
    ).toBeInTheDocument();
  });

  it("imports a reviewed provider configuration without exposing its contents", async () => {
    const importConfiguration = vi
      .spyOn(
        window.jobApplyPro.workbench,
        "selectAndImportProviderConfiguration",
      )
      .mockResolvedValue({
        source: "ENCRYPTED_DATABASE",
        providers: [
          {
            provider: "GMAIL",
            oauth_configured: true,
            requested_scopes: ["gmail.readonly"],
            read_enabled: true,
            write_enabled: false,
          },
        ],
        automatic_categories: [],
        updated_at: new Date(0).toISOString(),
      });

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /import provider config/i }),
    );

    expect(importConfiguration).toHaveBeenCalledOnce();
    expect(
      await screen.findByText(/configuration imported for 1 provider/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/gmail\.readonly/i)).not.toBeInTheDocument();
  });

  it("enables privacy-safe native notifications from the in-app center", async () => {
    vi.spyOn(
      window.jobApplyPro.workbench,
      "getDesktopNotificationStatus",
    ).mockResolvedValue({
      native_enabled: false,
      native_supported: true,
      poll_interval_seconds: 60,
      active_notifications: [
        {
          id: "workflow:one:MFA_REQUIRED:0",
          kind: "MFA_REQUIRED",
          title: "Sign-in verification required",
          body: "Open Job Apply Pro to review the protected local details.",
          destination: "WORKFLOWS",
          severity: "warning",
          occurred_at: new Date(0).toISOString(),
        },
      ],
      delivered_count: 0,
      last_checked_at: new Date(0).toISOString(),
      last_error: null,
    });
    const enable = vi
      .spyOn(window.jobApplyPro.workbench, "setNativeNotificationsEnabled")
      .mockResolvedValue({
        native_enabled: true,
        native_supported: true,
        poll_interval_seconds: 60,
        active_notifications: [],
        delivered_count: 1,
        last_checked_at: new Date(0).toISOString(),
        last_error: null,
      });

    render(<App />);
    expect(
      await screen.findByText("Sign-in verification required"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /enable/i }));

    expect(enable).toHaveBeenCalledWith(true);
    expect(await screen.findByText("WINDOWS ALERTS ON")).toBeInTheDocument();
    expect(screen.queryByText(/Secret Employer/i)).not.toBeInTheDocument();
  });
});
