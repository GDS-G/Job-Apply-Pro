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
  ApplicationFieldBinding,
  PortalRunSnapshot,
  SupervisedPortalRunSnapshot,
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

  it("shows the runtime Greenhouse form contract without claiming live compatibility", async () => {
    const binding = {
      id: "binding-email",
      application_id: discoveredWorkflow.application_id,
      application_answer_id: "answer-email",
      answer_revision: 2,
      portal: "GREENHOUSE",
      page_fingerprint: "gh-upload-pending",
      control_key: "email",
      control_kind: "EMAIL",
      label: "Email",
      required: true,
      options: [],
      canonical_field: "email",
      confidence: 1,
      binding_source: "USER_CONFIRMED",
      answer_source: "USER_REVIEWED",
      answer_kind: "EXACT",
      validation_rules: {},
      automation_permission: "AUTOFILL_ALLOWED",
      review_fingerprint: "b".repeat(64),
      created_at: discoveredWorkflow.updated_at,
      updated_at: discoveredWorkflow.updated_at,
    } satisfies ApplicationFieldBinding;
    const run: SupervisedPortalRunSnapshot = {
      id: "greenhouse-run",
      portal: "GREENHOUSE",
      workflow_id: discoveredWorkflow.workflow_id,
      browser_session_id: "greenhouse-browser",
      state: "AWAITING_USER",
      current_url:
        "https://job-boards.greenhouse.io/synthetic/jobs/100#documents",
      allowed_origins: ["https://job-boards.greenhouse.io"],
      page_fingerprint: "gh-upload-pending",
      disposition: "USER_ACTION_REQUIRED",
      intervention_reasons: ["USER_TAKEOVER"],
      evidence: [],
      observed_controls: [
        {
          index: 0,
          control_key: "email",
          kind: "EMAIL",
          tag: "input",
          input_type: "email",
          role: "",
          element_id: "email",
          field_name: "email",
          group_label: "",
          label: "Email",
          label_source: "LABEL",
          text: "",
          href: "",
          canonical_field: "email",
          section_path: [],
          repeat_group: "",
          repeat_index: null,
          repeat_count: 1,
          conditional_region: "",
          conditional_trigger: "",
          widget_popup: "",
          widget_expanded: null,
          widget_multiselectable: false,
          widget_searchable: false,
          widget_controls_one_visible_listbox: false,
          accept: "",
          checked: false,
          required: true,
          native_required: true,
          accessible_required: false,
          disabled: false,
          native_disabled: false,
          inherited_disabled: false,
          accessible_disabled: false,
          read_only: false,
          native_read_only: false,
          accessible_read_only: false,
          busy: false,
          control_busy: false,
          form_busy: false,
          inert: false,
          direct_inert: false,
          inherited_inert: false,
          accessibility_hidden: false,
          direct_accessibility_hidden: false,
          inherited_accessibility_hidden: false,
          visible: true,
          will_validate: true,
          constraint_satisfied: false,
          accessible_invalid: false,
          legal_attestation: false,
          character_limit: 320,
          minimum_number: null,
          maximum_number: null,
          earliest_date: null,
          latest_date: null,
          options: [],
          locator: { strategy: "LABEL", value: "Email", exact: true },
        },
      ],
      greenhouse_form: {
        policy_version: "greenhouse-form-execution-contract/1",
        page_fingerprint: "gh-upload-pending",
        page_type: "DOCUMENT_UPLOAD",
        stage: "DOCUMENTS",
        required_control_count: 3,
        satisfied_required_count: 0,
        review_field_count: 1,
        upload_review_count: 1,
        manual_intervention_count: 1,
        navigation_control_key: "documents-next",
        navigation_label: "Continue",
        ready_to_advance: false,
        controls: [
          {
            control_key: "email",
            label: "Email",
            control_kind: "EMAIL",
            required: true,
            blocking: true,
            action: "REVIEW_FIELD",
            postcondition: "VALUE_EQUALS",
            reason: "Sanitized fixture",
          },
          {
            control_key: "resume",
            label: "Resume",
            control_kind: "FILE_UPLOAD",
            required: true,
            blocking: true,
            action: "REVIEW_DOCUMENT_UPLOAD",
            postcondition: "UPLOAD_FILE_NAME_OBSERVED",
            reason: "Sanitized fixture",
          },
          {
            control_key: "location-widget",
            label: "Location search",
            control_kind: "CUSTOM",
            required: true,
            blocking: true,
            action: "USER_INTERVENTION",
            postcondition: "USER_VERIFIED",
            reason: "Sanitized custom-widget fixture",
          },
        ],
        limitations: ["Sanitized replay support is not live compatibility."],
        review_fingerprint: "c".repeat(64),
      },
      created_at: discoveredWorkflow.updated_at,
      updated_at: discoveredWorkflow.updated_at,
    };
    vi.spyOn(window.jobApplyPro.workbench, "listWorkflows").mockResolvedValue([
      discoveredWorkflow,
    ]);
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listSupervisedPortalRuns",
    ).mockResolvedValue([run]);
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listApplicationFieldBindings",
    ).mockResolvedValue([binding]);
    const execute = vi
      .spyOn(window.jobApplyPro.workbench, "executeGreenhouseFormAction")
      .mockResolvedValue(null);
    const executeField = vi
      .spyOn(window.jobApplyPro.workbench, "executeApplicationField")
      .mockResolvedValue(null);

    render(<App />);

    expect(
      await screen.findByText("Greenhouse documents form contract"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/0\/3 required controls satisfied/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/sanitized replay support is not live compatibility/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/manual handoff:/i)).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Review field binding" }),
    );
    expect(
      screen.getByLabelText("Detected control from current supervised page"),
    ).toHaveValue("email");
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review & populate exact field",
      }),
    );
    await waitFor(() =>
      expect(executeField).toHaveBeenCalledExactlyOnceWith(
        run.id,
        binding.id,
        run.page_fingerprint,
        run.greenhouse_form?.review_fingerprint,
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Review & upload document" }),
    );
    await waitFor(() =>
      expect(execute).toHaveBeenCalledExactlyOnceWith({
        application_id: discoveredWorkflow.application_id,
        run_id: run.id,
        action: "REVIEW_DOCUMENT_UPLOAD",
        control_key: "resume",
        form_review_fingerprint: run.greenhouse_form?.review_fingerprint,
      }),
    );
  });

  it("maps only a Greenhouse reviewed custom control to a single-select binding", async () => {
    const run: SupervisedPortalRunSnapshot = {
      id: "greenhouse-widget-run",
      portal: "GREENHOUSE",
      workflow_id: discoveredWorkflow.workflow_id,
      browser_session_id: "greenhouse-widget-browser",
      state: "AWAITING_USER",
      current_url:
        "https://job-boards.greenhouse.io/synthetic/jobs/100#questions",
      allowed_origins: ["https://job-boards.greenhouse.io"],
      page_fingerprint: "greenhouse-widget-page",
      disposition: "USER_ACTION_REQUIRED",
      intervention_reasons: [],
      evidence: [],
      observed_controls: [
        {
          index: 0,
          control_key: "work-location",
          kind: "CUSTOM",
          tag: "input",
          input_type: "text",
          role: "combobox",
          label: "Preferred work location",
          repeat_count: 1,
          widget_popup: "listbox",
          widget_expanded: true,
          widget_multiselectable: false,
          widget_searchable: true,
          widget_controls_one_visible_listbox: true,
          required: true,
          native_required: true,
          visible: true,
          options: [
            { value: "remote-internal", label: "Remote" },
            { value: "hybrid-internal", label: "Hybrid" },
          ],
          locator: {
            strategy: "LABEL",
            value: "Preferred work location",
            exact: true,
          },
        } as never,
      ],
      greenhouse_form: {
        policy_version: "greenhouse-form-execution-contract/1",
        page_fingerprint: "greenhouse-widget-page",
        page_type: "APPLICATION_FORM",
        stage: "APPLICATION",
        required_control_count: 1,
        satisfied_required_count: 0,
        review_field_count: 1,
        upload_review_count: 0,
        manual_intervention_count: 0,
        navigation_control_key: null,
        navigation_label: null,
        ready_to_advance: false,
        controls: [
          {
            control_key: "work-location",
            label: "Preferred work location",
            control_kind: "CUSTOM",
            required: true,
            blocking: true,
            action: "REVIEW_FIELD",
            postcondition: "VALUE_EQUALS",
            reason: "Bounded reviewed single-select widget",
          },
        ],
        limitations: [],
        review_fingerprint: "d".repeat(64),
      },
      created_at: discoveredWorkflow.updated_at,
      updated_at: discoveredWorkflow.updated_at,
    };
    vi.spyOn(window.jobApplyPro.workbench, "listWorkflows").mockResolvedValue([
      discoveredWorkflow,
    ]);
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listSupervisedPortalRuns",
    ).mockResolvedValue([run]);
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listApplicationAnswers",
    ).mockResolvedValue([
      {
        id: "answer-widget",
        application_id: discoveredWorkflow.application_id,
        profile_id: discoveredWorkflow.profile_id,
        job_id: "fixture-job",
        revision: 2,
        question: "Preferred work location",
        normalized_question: "preferred work location",
        canonical_field: "work_arrangement",
        answer_kind: "MULTIPLE_CHOICE",
        validation_rules: { choices: ["Remote", "Hybrid"] },
        answer: "Remote",
        status: "REVIEWED",
        source_type: "USER_REVIEWED",
        source_answer_id: null,
        library_answer_id: null,
        evidence_claim_ids: [],
        retrieval_results: [],
        provider_id: null,
        model_id: null,
        prompt_version: null,
        policy_version: "fixture",
        confidence: 1,
        character_limit: 200,
        character_limit_applied: false,
        limitations: [],
        user_edited: true,
        reuse_permission: "APPLICATIONS",
        created_at: discoveredWorkflow.updated_at,
        updated_at: discoveredWorkflow.updated_at,
      },
    ]);
    const preview = vi
      .spyOn(window.jobApplyPro.workbench, "previewApplicationFieldBinding")
      .mockRejectedValue(new Error("Captured expected preview input"));

    render(<App />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Review field binding" }),
    );
    expect(
      screen.getByRole("option", { name: /single select widget/i }),
    ).toHaveValue("work-location");
    const reviewedAnswerSelect = screen
      .getAllByLabelText("Reviewed application answer")
      .find((element) => element.tagName === "SELECT");
    expect(reviewedAnswerSelect).toBeDefined();
    fireEvent.change(reviewedAnswerSelect!, {
      target: { value: "answer-widget" },
    });
    const previewButton = screen.getByRole("button", {
      name: "Preview exact binding",
    });
    await waitFor(() => expect(previewButton).toBeEnabled());
    fireEvent.click(previewButton);

    await waitFor(() =>
      expect(preview).toHaveBeenCalledExactlyOnceWith({
        application_answer_id: "answer-widget",
        observed_field: {
          portal: "GREENHOUSE",
          page_fingerprint: run.page_fingerprint,
          control_key: "work-location",
          control_kind: "SINGLE_SELECT_WIDGET",
          label: "Preferred work location",
          required: true,
          options: ["Remote", "Hybrid"],
          character_limit: null,
          minimum_number: null,
          maximum_number: null,
          earliest_date: null,
          latest_date: null,
          legal_attestation: undefined,
        },
      }),
    );
  });

  it("submits a Greenhouse review only with the current provider contract", async () => {
    const run: SupervisedPortalRunSnapshot = {
      id: "greenhouse-submit-run",
      portal: "GREENHOUSE",
      workflow_id: discoveredWorkflow.workflow_id,
      browser_session_id: "greenhouse-submit-browser",
      state: "READY_TO_SUBMIT",
      current_url: "https://job-boards.greenhouse.io/synthetic/jobs/100#review",
      allowed_origins: ["https://job-boards.greenhouse.io"],
      page_fingerprint: "greenhouse-submit-page",
      disposition: "FINAL_CONFIRMATION_REQUIRED",
      intervention_reasons: ["FINAL_SUBMISSION"],
      evidence: [],
      observed_controls: [],
      greenhouse_form: {
        policy_version: "greenhouse-form-execution-contract/1",
        page_fingerprint: "greenhouse-submit-page",
        page_type: "SUBMISSION_REVIEW",
        stage: "REVIEW",
        required_control_count: 0,
        satisfied_required_count: 0,
        review_field_count: 0,
        upload_review_count: 0,
        manual_intervention_count: 0,
        navigation_control_key: null,
        navigation_label: null,
        ready_to_advance: false,
        controls: [
          {
            control_key: "submit",
            label: "Submit application",
            control_kind: "BUTTON",
            required: false,
            blocking: true,
            action: "FINAL_SUBMISSION_GATE",
            postcondition: "IDENTIFIER_BACKED_CONFIRMATION",
            reason: "Sanitized fixture",
          },
        ],
        limitations: ["Sanitized replay support is not live compatibility."],
        review_fingerprint: "d".repeat(64),
      },
      created_at: discoveredWorkflow.updated_at,
      updated_at: discoveredWorkflow.updated_at,
    };
    vi.spyOn(window.jobApplyPro.workbench, "listWorkflows").mockResolvedValue([
      discoveredWorkflow,
    ]);
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listSupervisedPortalRuns",
    ).mockResolvedValue([run]);
    const submit = vi
      .spyOn(window.jobApplyPro.workbench, "submitSupervisedPortal")
      .mockResolvedValue(null);

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Review & submit exact page" }),
    );
    await waitFor(() =>
      expect(submit).toHaveBeenCalledExactlyOnceWith(
        run.id,
        run.page_fingerprint,
        run.greenhouse_form?.review_fingerprint,
      ),
    );
  });

  it("keeps portal and candidate details scoped to the selected workflow", async () => {
    const secondWorkflow: WorkflowRunSnapshot = {
      ...discoveredWorkflow,
      workflow_id: "discovery-2",
      application_id: "application-2",
      profile_id: "profile-2",
      candidate_display_name: "Second synthetic candidate",
      employer: "Second example employer",
      title: "Second scoped role",
    };
    const secondRun: PortalRunSnapshot = {
      id: "fixture-run-2",
      portal: "REFERENCE_ATS",
      capabilities: [],
      workflow_id: secondWorkflow.workflow_id,
      application_id: secondWorkflow.application_id,
      browser_session_id: "fixture-browser-2",
      profile_id: secondWorkflow.profile_id,
      job_id: "fixture-job-2",
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
      selected_document_version_id: "fixture-version-2",
      field_mappings: [],
      review_fingerprint: "b".repeat(64),
      created_at: secondWorkflow.updated_at,
      updated_at: secondWorkflow.updated_at,
    };
    const api = window.jobApplyPro.workbench;
    vi.spyOn(api, "listWorkflows").mockResolvedValue([
      discoveredWorkflow,
      secondWorkflow,
    ]);
    vi.spyOn(api, "listPortalRuns").mockResolvedValue([secondRun]);
    const getKnowledge = vi
      .spyOn(api, "getCandidateKnowledge")
      .mockImplementation(async (profileId) => ({
        profile_id: profileId,
        documents: [],
        claims: [],
        answers: [],
      }));
    const listAnswers = vi.spyOn(api, "listApplicationAnswers");
    const listBindings = vi.spyOn(api, "listApplicationFieldBindings");
    const listExecutions = vi.spyOn(api, "listApplicationFieldExecutions");

    render(<App />);

    await screen.findByRole("heading", {
      name: "Guided application workspace",
    });
    expect(screen.queryByText("Fit 100%")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Confirm fixture submission" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Second scoped role/ }));

    await waitFor(() => {
      expect(getKnowledge).toHaveBeenCalledWith("profile-2");
      expect(listAnswers).toHaveBeenCalledWith("application-2");
      expect(listBindings).toHaveBeenCalledWith("application-2");
      expect(listExecutions).toHaveBeenCalledWith("application-2");
    });
    expect(await screen.findByText("Fit 100%")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Confirm fixture submission" }),
    ).toBeInTheDocument();
    for (const selector of screen.getAllByLabelText("Target application")) {
      expect(selector).toHaveValue("application-2");
    }
    expect(screen.getByText(/Application application-2/)).toBeInTheDocument();
  });

  it("shows the Workbench safety boundary", async () => {
    render(<App />);

    expect(
      screen.getByText(
        "Reviewed Browser Navigation Reconciliation v0.76.0-alpha.1",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Guided application workspace" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/backend state, allowed actions, review fingerprints/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/production application submission remains disabled/i),
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
      screen.getByText(/external effects requiring attention/i),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        /provider or browser outcome must be reconciled/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/safe code: provider_response_unavailable/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /retry external effect/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /clear external effect/i }),
    ).not.toBeInTheDocument();
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

  it("shows reusable portal profiles without claiming to store login credentials", async () => {
    const api = window.jobApplyPro.workbench;
    const sessionId = "7193b158-26dd-4abc-9f25-bd45f0e67382";
    vi.spyOn(api, "listWorkflows").mockResolvedValue([discoveredWorkflow]);
    vi.spyOn(api, "listBrowserSessions").mockResolvedValue([
      {
        id: sessionId,
        workflow_id: discoveredWorkflow.workflow_id,
        engine: "msedge",
        profile_name: "workday-tenant-a",
        state: "STOPPED",
        current_url: "https://tenant.wd5.myworkdayjobs.com/jobs",
        allowed_origins: ["https://tenant.wd5.myworkdayjobs.com"],
        observation: null,
        action_count: 0,
        trace_path: null,
        created_at: discoveredWorkflow.updated_at,
        updated_at: discoveredWorkflow.updated_at,
      },
    ]);
    vi.spyOn(api, "listBrowserProfiles").mockResolvedValue([
      {
        engine: "msedge",
        profile_name: "workday-tenant-a",
        state: "AVAILABLE",
        allowed_origins: ["https://tenant.wd5.myworkdayjobs.com"],
        session_count: 1,
        last_used_at: discoveredWorkflow.updated_at,
        pending_cleanup_id: null,
      },
    ]);
    vi.spyOn(api, "listSupervisedPortalRuns").mockResolvedValue([
      {
        id: "workday-run",
        portal: "WORKDAY",
        workflow_id: discoveredWorkflow.workflow_id,
        browser_session_id: sessionId,
        state: "STOPPED",
        current_url: "https://tenant.wd5.myworkdayjobs.com/jobs",
        allowed_origins: ["https://tenant.wd5.myworkdayjobs.com"],
        page_fingerprint: "workday-stopped",
        current_match: null,
        disposition: "STOPPED",
        intervention_reasons: [],
        evidence: [],
        observed_controls: [],
        greenhouse_form: null,
        trace_path: "C:/fixture/workday-trace.zip",
        created_at: discoveredWorkflow.updated_at,
        updated_at: discoveredWorkflow.updated_at,
      } satisfies SupervisedPortalRunSnapshot,
    ]);
    const retire = vi.spyOn(api, "retireBrowserProfile").mockResolvedValue({
      engine: "msedge",
      profile_name: "workday-tenant-a",
      removed: true,
      retired_at: discoveredWorkflow.updated_at,
      notice: "Local browser profile data was removed.",
    });

    render(<App />);

    const saved = await screen.findByRole("region", {
      name: "Saved supervised portal profiles",
    });
    expect(saved).toHaveTextContent("workday-tenant-a");
    expect(saved).toHaveTextContent("WORKDAY · msedge");
    expect(saved).toHaveTextContent("Origin bound");
    expect(saved).toHaveTextContent("https://tenant.wd5.myworkdayjobs.com");
    expect(
      document.querySelector(
        'datalist#saved-portal-profile-names option[value="workday-tenant-a"]',
      ),
    ).not.toBeNull();
    expect(
      screen.getByText(/never stores or auto-fills the portal password/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Retire local profile data" }),
    ).toBeEnabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Retire local profile data" }),
    );
    await waitFor(() =>
      expect(retire).toHaveBeenCalledExactlyOnceWith(
        "msedge",
        "workday-tenant-a",
      ),
    );
    expect(
      await screen.findByText("Local browser profile data was removed."),
    ).toBeInTheDocument();
  });

  it("offers native-reviewed recovery for an isolated profile cleanup", async () => {
    const api = window.jobApplyPro.workbench;
    const sessionId = "75ce83a8-5a39-40de-ad09-e619285609b4";
    const cleanupId = "d1c5770b-22b0-4e97-81ee-722f9d9ad947";
    vi.spyOn(api, "listWorkflows").mockResolvedValue([discoveredWorkflow]);
    vi.spyOn(api, "listBrowserSessions").mockResolvedValue([
      {
        id: sessionId,
        workflow_id: discoveredWorkflow.workflow_id,
        engine: "msedge",
        profile_name: "workday-cleanup-pending",
        state: "STOPPED",
        current_url: "https://tenant.wd5.myworkdayjobs.com/jobs",
        allowed_origins: ["https://tenant.wd5.myworkdayjobs.com"],
        observation: null,
        action_count: 0,
        trace_path: null,
        created_at: discoveredWorkflow.updated_at,
        updated_at: discoveredWorkflow.updated_at,
      },
    ]);
    vi.spyOn(api, "listBrowserProfiles").mockResolvedValue([
      {
        engine: "msedge",
        profile_name: "workday-cleanup-pending",
        state: "CLEANUP_PENDING",
        allowed_origins: ["https://tenant.wd5.myworkdayjobs.com"],
        session_count: 1,
        last_used_at: discoveredWorkflow.updated_at,
        pending_cleanup_id: cleanupId,
      },
    ]);
    vi.spyOn(api, "listSupervisedPortalRuns").mockResolvedValue([
      {
        id: "workday-cleanup-run",
        portal: "WORKDAY",
        workflow_id: discoveredWorkflow.workflow_id,
        browser_session_id: sessionId,
        state: "STOPPED",
        current_url: "https://tenant.wd5.myworkdayjobs.com/jobs",
        allowed_origins: ["https://tenant.wd5.myworkdayjobs.com"],
        page_fingerprint: "workday-cleanup-stopped",
        current_match: null,
        disposition: "STOPPED",
        intervention_reasons: [],
        evidence: [],
        observed_controls: [],
        greenhouse_form: null,
        trace_path: "C:/fixture/workday-cleanup-trace.zip",
        created_at: discoveredWorkflow.updated_at,
        updated_at: discoveredWorkflow.updated_at,
      } satisfies SupervisedPortalRunSnapshot,
    ]);
    const finishCleanup = vi
      .spyOn(api, "cleanupBrowserProfile")
      .mockResolvedValue({
        engine: "msedge",
        profile_name: "workday-cleanup-pending",
        cleanup_id: cleanupId,
        removed: true,
        cleaned_at: discoveredWorkflow.updated_at,
        notice: "Isolated local browser profile data was removed.",
      });

    render(<App />);

    const saved = await screen.findByRole("region", {
      name: "Saved supervised portal profiles",
    });
    expect(saved).toHaveTextContent("Cleanup pending");
    expect(
      screen.queryByRole("button", { name: "Retire local profile data" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Finish isolated profile cleanup",
      }),
    );
    await waitFor(() =>
      expect(finishCleanup).toHaveBeenCalledExactlyOnceWith(
        "msedge",
        "workday-cleanup-pending",
        cleanupId,
      ),
    );
    expect(
      await screen.findByText(
        "Isolated local browser profile data was removed.",
      ),
    ).toBeInTheDocument();
  });

  it("offers reviewed field reconciliation only for an eligible takeover session", async () => {
    const api = window.jobApplyPro.workbench;
    const operationId = "64a4cc96-07d1-4a0e-8000-a74811a13c0e";
    const attemptId = "19c70be6-ea1b-4c71-b668-d359f7ce4b06";
    const sessionId = "5fdf419a-0771-4d75-99d2-c76ba2f89719";
    const operations = await api.getOperationsDashboard();
    vi.spyOn(api, "listBrowserSessions").mockResolvedValue([
      {
        id: sessionId,
        workflow_id: "fixture-workflow",
        engine: "chromium",
        profile_name: "fixture-profile",
        state: "USER_TAKEOVER",
        current_url: "https://boards.greenhouse.io/example/jobs/123",
        allowed_origins: ["https://boards.greenhouse.io"],
        observation: null,
        action_count: 1,
        trace_path: null,
        created_at: new Date(0).toISOString(),
        updated_at: new Date(0).toISOString(),
      },
    ]);
    vi.spyOn(api, "getOperationsDashboard").mockResolvedValue({
      ...operations,
      external_effects: {
        total: 1,
        unresolved: 1,
        by_status: { UNCERTAIN: 1 },
        by_kind: { BROWSER_ACTION: 1 },
      },
      unresolved_external_effects: [
        {
          id: operationId,
          kind: "BROWSER_ACTION",
          subject_type: "browser_session",
          subject_id: sessionId,
          status: "UNCERTAIN",
          error_code: "WORKER_RESPONSE_UNAVAILABLE",
          attempt_count: 1,
          created_at: new Date(0).toISOString(),
          updated_at: new Date(0).toISOString(),
          completed_at: new Date(0).toISOString(),
          reconciliation_available: true,
          reconciliation_kind: "BROWSER_FIELD_VALUE_CONFIRMED",
        },
      ],
    });
    const reconcile = vi.spyOn(api, "reconcileBrowserField").mockResolvedValue({
      operation_id: operationId,
      attempt_id: attemptId,
      session_id: sessionId,
      action_kind: "FILL",
      page_fingerprint: "greenhouse:questionnaire:ab12cd34",
      reconciliation_kind: "BROWSER_FIELD_VALUE_CONFIRMED",
      reconciled_at: "2026-09-15T18:00:00+00:00",
      notice: "Verified field outcome recorded without repeating the action.",
    });

    render(<App />);
    const button = await screen.findByRole("button", {
      name: /verify current field outcome/i,
    });
    fireEvent.click(button);

    await waitFor(() =>
      expect(reconcile).toHaveBeenCalledExactlyOnceWith(operationId, sessionId),
    );
    expect(
      await screen.findByText(/recorded without repeating the action/i),
    ).toBeInTheDocument();
  });

  it("offers reviewed navigation reconciliation for a matching takeover session", async () => {
    const api = window.jobApplyPro.workbench;
    const operationId = "74a4cc96-07d1-4a0e-8000-a74811a13c0e";
    const attemptId = "29c70be6-ea1b-4c71-b668-d359f7ce4b06";
    const sessionId = "6fdf419a-0771-4d75-99d2-c76ba2f89719";
    const operations = await api.getOperationsDashboard();
    vi.spyOn(api, "listBrowserSessions").mockResolvedValue([
      {
        id: sessionId,
        workflow_id: "fixture-workflow",
        engine: "chromium",
        profile_name: "fixture-navigation-profile",
        state: "USER_TAKEOVER",
        current_url: "https://boards.greenhouse.io/example/jobs/123",
        allowed_origins: ["https://boards.greenhouse.io"],
        observation: null,
        action_count: 1,
        trace_path: null,
        created_at: new Date(0).toISOString(),
        updated_at: new Date(0).toISOString(),
      },
    ]);
    vi.spyOn(api, "getOperationsDashboard").mockResolvedValue({
      ...operations,
      external_effects: {
        total: 1,
        unresolved: 1,
        by_status: { UNCERTAIN: 1 },
        by_kind: { BROWSER_ACTION: 1 },
      },
      unresolved_external_effects: [
        {
          id: operationId,
          kind: "BROWSER_ACTION",
          subject_type: "browser_session",
          subject_id: sessionId,
          status: "UNCERTAIN",
          error_code: "WORKER_RESPONSE_UNAVAILABLE",
          attempt_count: 1,
          created_at: new Date(0).toISOString(),
          updated_at: new Date(0).toISOString(),
          completed_at: new Date(0).toISOString(),
          reconciliation_available: true,
          reconciliation_kind: "BROWSER_NAVIGATION_CONFIRMED",
        },
      ],
    });
    const reconcile = vi
      .spyOn(api, "reconcileBrowserNavigation")
      .mockResolvedValue({
        operation_id: operationId,
        attempt_id: attemptId,
        session_id: sessionId,
        source_page_type: "APPLICATION_FORM",
        result_page_type: "DOCUMENT_UPLOAD",
        result_page_fingerprint: "greenhouse-documents-v2",
        reconciliation_kind: "BROWSER_NAVIGATION_CONFIRMED",
        reconciled_at: "2026-09-15T19:00:00+00:00",
        notice: "Reviewed navigation recorded without retrying the action.",
      });

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: /verify current form stage/i,
      }),
    );

    await waitFor(() =>
      expect(reconcile).toHaveBeenCalledExactlyOnceWith(operationId, sessionId),
    );
    expect(
      await screen.findByText(/recorded without retrying the action/i),
    ).toBeInTheDocument();
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

  it.each([
    { matchedRequirementIds: [] },
    { matchedRequirementIds: ["legacy-match"] },
  ])(
    "does not infer qualification from an empty missing-requirements list ($matchedRequirementIds)",
    async ({ matchedRequirementIds }) => {
      const api = window.jobApplyPro.workbench;
      vi.spyOn(api, "listWorkflows").mockResolvedValue([
        { ...discoveredWorkflow, state: "DEDUPLICATED", allowed_controls: [] },
      ]);
      vi.spyOn(api, "getCandidateKnowledge").mockResolvedValue({
        profile_id: discoveredWorkflow.profile_id,
        documents: [],
        answers: [],
        claims: [
          {
            id: "reviewed-claim",
            profile_id: discoveredWorkflow.profile_id,
            canonical_key: "python",
            statement: "User-reviewed Python experience",
            claim_type: "skill",
            value: {},
            context: {},
            confidence: 1,
            verification_status: "VERIFIED",
            permitted_use: "APPLICATIONS",
            sensitivity: "PERSONAL",
            locked: true,
            created_at: discoveredWorkflow.updated_at,
            updated_at: discoveredWorkflow.updated_at,
          },
        ],
      });
      vi.spyOn(api, "previewTailoredDocument").mockResolvedValue({
        application_id: discoveredWorkflow.application_id,
        profile_id: discoveredWorkflow.profile_id,
        job_id: "imported-job",
        employer: discoveredWorkflow.employer,
        title: discoveredWorkflow.title,
        kind: "RESUME",
        output_format: "DOCX",
        variant_label: "Tailored evidence",
        template: "PROFESSIONAL",
        ranking_mode: "DETERMINISTIC",
        ranking_method: "deterministic-v1",
        sections: [],
        selected_claim_ids: ["reviewed-claim"],
        matched_requirement_ids: matchedRequirementIds,
        missing_required_requirements: [],
        review_fingerprint: "a".repeat(64),
      });
      const generate = vi.spyOn(api, "generateTailoredDocument");
      const qualification = vi.spyOn(api, "approveJobQualification");
      render(<App />);
      const button = screen.getByRole("button", { name: "Preview evidence" });
      await waitFor(() => expect(button).not.toBeDisabled());
      fireEvent.click(button);
      expect(
        await screen.findByText(
          /Requirements may be absent or unreviewed; eligibility is not established/,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          /For imported Greenhouse jobs, use Reviewed job readiness to review qualification against the saved source/,
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByText("No required qualification is unmatched."),
      ).not.toBeInTheDocument();
      expect(generate).not.toHaveBeenCalled();
      expect(qualification).not.toHaveBeenCalled();
    },
  );

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

  it.each([false, true])(
    "keeps connected calendar write=%s sync-only and reports reconciliation counts",
    async (writeEnabled) => {
      vi.spyOn(
        window.jobApplyPro.workbench,
        "listIntegrationHealth",
      ).mockResolvedValue([
        {
          provider: "GOOGLE_CALENDAR",
          status: "CONNECTED",
          message: "Provider adapter is connected",
          read_enabled: true,
          write_enabled: writeEnabled,
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
      expect(
        screen.queryByRole("button", {
          name: /create event|update event|confirm calendar|execute calendar/i,
        }),
      ).not.toBeInTheDocument();
    },
  );

  it("shows calendar creation only with configured and actually granted write capability", async () => {
    vi.spyOn(
      window.jobApplyPro.workbench,
      "getProviderConfigurationStatus",
    ).mockResolvedValue({
      source: "ENCRYPTED_DATABASE",
      providers: [
        {
          provider: "GOOGLE_CALENDAR",
          oauth_configured: true,
          requested_scopes: ["https://www.googleapis.com/auth/calendar.events"],
          read_enabled: true,
          write_enabled: true,
        },
      ],
      automatic_categories: [],
      updated_at: "2026-09-13T10:00:00.000Z",
    });
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listIntegrationHealth",
    ).mockResolvedValue([
      {
        provider: "GOOGLE_CALENDAR",
        status: "CONNECTED",
        message: "Provider adapter is connected",
        read_enabled: true,
        write_enabled: true,
        granted_scopes: ["https://www.googleapis.com/auth/calendar.events"],
        account_hint: "candidate@example.invalid",
      },
    ]);

    render(<App />);

    expect(
      await screen.findByRole("heading", {
        name: "Reviewed calendar event creation",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/attendee/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Fixed event policy/i)).toHaveTextContent(
      /private.*busy.*reminders are disabled.*attendees.*none/i,
    );
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
