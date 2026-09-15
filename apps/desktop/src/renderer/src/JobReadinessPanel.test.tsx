import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  GreenhouseApplicationLaunchPreview,
  JobReadinessSnapshot,
  QualificationPreview,
  RequirementsPreview,
  SupervisedPortalRunSnapshot,
} from "@job-apply-pro/contracts";
import { JobReadinessPanel } from "./JobReadinessPanel";

const digest = "a".repeat(64);
const spanId = "b".repeat(64);
const requirementId = "c".repeat(64);
const requirements: RequirementsPreview = {
  application_id: "app-1",
  job_id: "job-1",
  source_fingerprint: digest,
  requirements: [
    {
      id: requirementId,
      span_id: spanId,
      text: "Python experience",
      classification: "MANDATORY",
    },
  ],
  requirements_fingerprint: digest,
  review_fingerprint: "d".repeat(64),
  notice: "Review the exact source requirements.",
};
const qualification: QualificationPreview = {
  application_id: "app-1",
  requirements_review_id: "requirements-1",
  requirements_fingerprint: digest,
  candidate_fingerprint: digest,
  policy_version: "reviewed-job-readiness/1",
  findings: [
    {
      requirement_id: requirementId,
      text: "Python experience",
      classification: "MANDATORY",
      status: "SUPPORTED",
      claim_ids: ["claim-1"],
    },
  ],
  mandatory_count: 1,
  mandatory_supported: 1,
  preferred_count: 0,
  preferred_supported: 0,
  coverage_score: 1,
  evaluable: true,
  eligible: true,
  review_fingerprint: "e".repeat(64),
  notice: "Local user-reviewed evidence only.",
};
const snapshot: JobReadinessSnapshot = {
  application_id: "app-1",
  job_id: "job-1",
  profile_id: "profile-1",
  workflow_id: "workflow-1",
  state: "DEDUPLICATED",
  supported: true,
  status: "REQUIREMENTS_REVIEW",
  source_fingerprint: digest,
  source: {
    board_token: "Synthetic",
    posting_id: "12",
    title: "Engineer",
    employer: "Example",
    location: null,
    source_url: null,
    navigation_supported: false,
    description:
      '<script>untrusted()</script><img src="https://pixel.invalid">',
    api_url: "https://boards-api.greenhouse.io/v1/boards/Synthetic/jobs/12",
    reported_url: "https://employer.invalid/job/12",
    provider_updated_at: null,
    fetched_at: "2026-09-12T12:00:00Z",
    normalizer_version: "greenhouse-v1",
    review_fingerprint: digest,
    qualification_status: "NOT_EVALUATED",
  },
  spans: [{ id: spanId, text: "Python experience" }],
  evidence_claims: [
    {
      id: "claim-1",
      profile_id: "profile-1",
      canonical_key: "python",
      statement: "Reviewed Python project experience",
      claim_type: "skill",
      value: {},
      context: {},
      confidence: 1,
      verification_status: "VERIFIED",
      permitted_use: "APPLICATIONS",
      sensitivity: "PERSONAL",
      locked: true,
      created_at: "2026-09-12T12:00:00Z",
      updated_at: "2026-09-12T12:00:00Z",
    },
  ],
  requirements_review: null,
  qualification_review: null,
  selection_review: null,
  allowed_actions: ["REVIEW_REQUIREMENTS"],
  notice: "Qualification is not evaluated.",
};
const withRequirements: JobReadinessSnapshot = {
  ...snapshot,
  status: "QUALIFICATION_REVIEW",
  requirements_review: {
    ...requirements,
    id: "requirements-1",
    revision: 1,
    created_at: "2026-09-12T12:00:00Z",
  },
  allowed_actions: ["REVIEW_REQUIREMENTS", "REVIEW_QUALIFICATION"],
};
const withEligibility: JobReadinessSnapshot = {
  ...withRequirements,
  state: "ELIGIBILITY_CHECKED",
  status: "RESUME_REVIEW",
  qualification_review: {
    ...qualification,
    id: "qualification-1",
    revision: 1,
    created_at: "2026-09-12T12:00:00Z",
    eligibility_approved: true,
  },
  allowed_actions: [
    "REVIEW_REQUIREMENTS",
    "REVIEW_QUALIFICATION",
    "SELECT_RESUME",
  ],
};
const withReady: JobReadinessSnapshot = {
  ...withEligibility,
  state: "DOCUMENTS_SELECTED",
  status: "READY",
  source: {
    ...withEligibility.source!,
    source_url: "https://job-boards.greenhouse.io/example/jobs/12",
    navigation_supported: true,
  },
  selection_review: {
    id: "selection-1",
    revision: 1,
    created_at: "2026-09-12T12:00:00Z",
    application_id: "app-1",
    requirements_review_id: "requirements-1",
    qualification_review_id: "qualification-1",
    requirements_fingerprint: digest,
    candidate_fingerprint: digest,
    document_fingerprint: digest,
    document_version_id: "version-1",
    review_fingerprint: "f".repeat(64),
    policy_version: "reviewed-resume-selection/1",
  },
};
const launchPreview: GreenhouseApplicationLaunchPreview = {
  application_id: "app-1",
  workflow_id: "workflow-1",
  profile_id: "profile-1",
  job_id: "job-1",
  employer: "Example",
  title: "Engineer",
  start_url: "https://job-boards.greenhouse.io/example/jobs/12",
  start_origin: "https://job-boards.greenhouse.io",
  selected_document_version_id: "version-1",
  source_fingerprint: digest,
  requirements_review_id: "requirements-1",
  qualification_review_id: "qualification-1",
  selection_review_id: "selection-1",
  policy_version: "reviewed-greenhouse-application-launch/1",
  review_fingerprint: "9".repeat(64),
  notice: "Opens a visible browser and does not submit.",
};
const greenhouseRun = {
  id: "greenhouse-run-1",
  portal: "GREENHOUSE",
  workflow_id: "workflow-1",
  browser_session_id: "browser-1",
  state: "AWAITING_USER",
  current_url: launchPreview.start_url,
  allowed_origins: [launchPreview.start_origin],
  page_fingerprint: "page-1",
  current_match: null,
  disposition: "USER_ACTION_REQUIRED",
  intervention_reasons: ["USER_TAKEOVER"],
  evidence: [],
  observed_controls: [],
  trace_path: null,
  created_at: "2026-09-12T12:00:00Z",
  updated_at: "2026-09-12T12:00:00Z",
} satisfies SupervisedPortalRunSnapshot;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("Reviewed job readiness panel", () => {
  const api = window.jobApplyPro.workbench;
  const changed = vi.fn();
  const portalStarted = vi.fn();
  beforeEach(() => {
    changed.mockReset();
    portalStarted.mockReset();
    vi.spyOn(api, "getJobReadiness").mockResolvedValue(snapshot);
    vi.spyOn(api, "previewJobRequirements").mockResolvedValue(requirements);
    vi.spyOn(api, "approveJobRequirements").mockResolvedValue(withRequirements);
    vi.spyOn(api, "previewJobQualification").mockResolvedValue(qualification);
    vi.spyOn(api, "approveJobQualification").mockResolvedValue(withEligibility);
    vi.spyOn(api, "approveJobResume").mockResolvedValue(null);
    vi.spyOn(api, "previewGreenhouseApplicationLaunch").mockResolvedValue(
      launchPreview,
    );
    vi.spyOn(api, "startGreenhouseApplicationLaunch").mockResolvedValue(
      greenhouseRun,
    );
    vi.spyOn(api, "previewJobResume").mockResolvedValue({
      selection: {
        application_id: "app-1",
        profile_id: "profile-1",
        job_id: "job-1",
        employer: "Example",
        title: "Engineer",
        current_document_version_id: null,
        recommended_document_version_id: "version-1",
        recommendations: [
          {
            document_id: "document-1",
            document_version_id: "version-1",
            display_name: "Resume",
            variant_label: "Platform",
            score: 0.8,
            matched_job_family_tags: [],
            matched_requirement_ids: [requirementId],
            reasons: ["One source requirement matched"],
            is_primary: true,
          },
        ],
        review_fingerprint: "inner-fingerprint",
      },
      requirements_review_id: "requirements-1",
      qualification_review_id: "qualification-1",
      review_fingerprint: "f".repeat(64),
      notice: "Choose an immutable version.",
    });
    vi.spyOn(api, "controlWorkflow");
    vi.spyOn(api, "reviewGreenhouseJob");
    vi.spyOn(api, "previewDocumentSelection");
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });
  function panel() {
    return render(
      <JobReadinessPanel
        backendReady
        applicationId="app-1"
        profileId="profile-1"
        onChanged={changed}
        onPortalStarted={portalStarted}
      />,
    );
  }
  async function load(value = snapshot) {
    vi.mocked(api.getJobReadiness).mockResolvedValue(value);
    fireEvent.click(
      screen.getByRole("button", { name: "Load saved job evidence" }),
    );
    await screen.findByText(/Review status:/);
  }

  it("only loads explicitly, renders source as text, and never advances or contacts a live source", async () => {
    const view = panel();
    expect(api.getJobReadiness).not.toHaveBeenCalled();
    await load();
    expect(view.container.querySelector("script, img, iframe, a")).toBeNull();
    expect(screen.getByText(snapshot.source!.description)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Classification for passage 1"), {
      target: { value: "MANDATORY" },
    });
    expect(api.previewJobRequirements).not.toHaveBeenCalled();
    expect(api.reviewGreenhouseJob).not.toHaveBeenCalled();
    expect(api.controlWorkflow).not.toHaveBeenCalled();
    expect(api.previewDocumentSelection).not.toHaveBeenCalled();
  });

  it("previews exact span identifiers and approves only the captured backend fingerprint", async () => {
    panel();
    await load();
    fireEvent.change(screen.getByLabelText("Classification for passage 1"), {
      target: { value: "MANDATORY" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview source requirements" }),
    );
    const approve = await screen.findByRole("button", {
      name: "Review & approve requirements",
    });
    const input = {
      application_id: "app-1",
      source_fingerprint: digest,
      items: [{ span_id: spanId, classification: "MANDATORY" }],
    };
    expect(api.previewJobRequirements).toHaveBeenCalledExactlyOnceWith(input);
    expect(api.approveJobRequirements).not.toHaveBeenCalled();
    fireEvent.click(approve);
    await screen.findByText(/Saved requirements revision 1/);
    expect(api.approveJobRequirements).toHaveBeenCalledExactlyOnceWith({
      input,
      review_fingerprint: requirements.review_fingerprint,
    });
    expect(changed).toHaveBeenCalledTimes(1);
    expect(api.controlWorkflow).not.toHaveBeenCalled();
  });

  it("clears requirement approval when any classification changes", async () => {
    panel();
    await load();
    fireEvent.click(
      screen.getByRole("button", { name: "Preview source requirements" }),
    );
    await screen.findByRole("button", {
      name: "Review & approve requirements",
    });
    fireEvent.change(screen.getByLabelText("Classification for passage 1"), {
      target: { value: "AMBIGUOUS" },
    });
    expect(
      screen.queryByRole("button", { name: "Review & approve requirements" }),
    ).not.toBeInTheDocument();
    expect(api.approveJobRequirements).not.toHaveBeenCalled();
  });

  it("defaults findings to unknown and requires reviewed claim links for support", async () => {
    panel();
    await load(withRequirements);
    expect(
      screen.getByLabelText("Evidence finding for requirement 1"),
    ).toHaveValue("UNKNOWN");
    expect(
      screen.getByLabelText(/Reviewed Python project experience/),
    ).toBeDisabled();
    fireEvent.change(
      screen.getByLabelText("Evidence finding for requirement 1"),
      { target: { value: "SUPPORTED" } },
    );
    expect(
      screen.getByRole("button", { name: "Preview evidence assessment" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByLabelText(/Reviewed Python project experience/),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Preview evidence assessment" }),
    );
    await screen.findByRole("button", {
      name: "Review & save qualification decision",
    });
    expect(api.previewJobQualification).toHaveBeenCalledExactlyOnceWith({
      application_id: "app-1",
      requirements_review_id: "requirements-1",
      findings: [
        {
          requirement_id: requirementId,
          status: "SUPPORTED",
          claim_ids: ["claim-1"],
        },
      ],
    });
    expect(
      screen.getByLabelText(/I reviewed these local criteria/),
    ).not.toBeChecked();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review & save qualification decision",
      }),
    );
    await waitFor(() =>
      expect(api.approveJobQualification).toHaveBeenCalledTimes(1),
    );
    expect(api.approveJobQualification).toHaveBeenCalledWith(
      expect.objectContaining({
        approve_eligibility: false,
        review_fingerprint: qualification.review_fingerprint,
      }),
    );
  });

  it("requires explicit eligibility opt-in and never presents an unevaluable result as perfect", async () => {
    vi.mocked(api.previewJobQualification).mockResolvedValue({
      ...qualification,
      eligible: false,
      evaluable: false,
      coverage_score: null,
      mandatory_count: 0,
      mandatory_supported: 0,
      findings: [],
    });
    panel();
    await load({
      ...withRequirements,
      requirements_review: {
        ...withRequirements.requirements_review!,
        requirements: [],
      },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview evidence assessment" }),
    );
    await screen.findByText("Coverage is not evaluable.");
    expect(
      screen.getByLabelText(/I reviewed these local criteria/),
    ).toBeDisabled();
    expect(screen.queryByText(/coverage: 100%/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Preview readiness resume ranking" }),
    ).toBeDisabled();
  });

  it("uses readiness-specific resume preview and its outer approval fingerprint", async () => {
    panel();
    await load(withEligibility);
    fireEvent.click(
      screen.getByRole("button", { name: "Preview readiness resume ranking" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Review & select Platform" }),
    );
    await screen.findByText(/approval was cancelled/);
    expect(api.approveJobResume).toHaveBeenCalledExactlyOnceWith({
      input: {
        application_id: "app-1",
        kind: "RESUME",
        preferred_tags: [],
        excluded_document_ids: [],
        prefer_primary: true,
      },
      review_fingerprint: "f".repeat(64),
      document_version_id: "version-1",
    });
    expect(changed).not.toHaveBeenCalled();
    expect(api.previewDocumentSelection).not.toHaveBeenCalled();
    expect(api.controlWorkflow).not.toHaveBeenCalled();
  });

  it("opens only the exact backend-reviewed Greenhouse application after readiness", async () => {
    panel();
    await load(withReady);
    expect(
      screen.getByRole("button", { name: "Review Greenhouse launch" }),
    ).toBeInTheDocument();
    expect(api.previewGreenhouseApplicationLaunch).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Review Greenhouse launch" }),
    );
    const open = await screen.findByRole("button", {
      name: "Open reviewed Greenhouse application",
    });
    expect(
      api.previewGreenhouseApplicationLaunch,
    ).toHaveBeenCalledExactlyOnceWith("app-1");
    expect(screen.getByText(/Exact allowed origin:/)).toHaveTextContent(
      launchPreview.start_origin,
    );
    fireEvent.click(open);
    await waitFor(() =>
      expect(portalStarted).toHaveBeenCalledWith(greenhouseRun),
    );
    expect(
      api.startGreenhouseApplicationLaunch,
    ).toHaveBeenCalledExactlyOnceWith({
      application_id: "app-1",
      review_fingerprint: launchPreview.review_fingerprint,
      profile_name: "greenhouse-profile",
      engine: "msedge",
    });
    expect(
      screen.getByText(
        "The reviewed Greenhouse posting is open in a visible supervised browser. No application was submitted.",
      ),
    ).toBeInTheDocument();
  });

  it("sends eligibility clearance only after a separate explicit checkbox choice", async () => {
    panel();
    await load(withEligibility);
    fireEvent.click(
      screen.getByRole("button", { name: "Preview evidence assessment" }),
    );
    const checkbox = await screen.findByLabelText(
      /I reviewed these local criteria/,
    );
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review & save qualification decision",
      }),
    );
    await waitFor(() =>
      expect(api.approveJobQualification).toHaveBeenCalledTimes(1),
    );
    expect(api.approveJobQualification).toHaveBeenCalledWith(
      expect.objectContaining({ approve_eligibility: true }),
    );
  });

  it("ignores a requirements preview that arrives after a target change", async () => {
    const old = deferred<RequirementsPreview>();
    vi.mocked(api.previewJobRequirements).mockReturnValueOnce(old.promise);
    const view = panel();
    await load();
    fireEvent.click(
      screen.getByRole("button", { name: "Preview source requirements" }),
    );
    view.rerender(
      <JobReadinessPanel
        backendReady
        applicationId="app-2"
        profileId="profile-1"
        onChanged={changed}
      />,
    );
    await act(async () => old.resolve(requirements));
    expect(
      screen.queryByRole("button", { name: "Review & approve requirements" }),
    ).not.toBeInTheDocument();
    expect(api.approveJobRequirements).not.toHaveBeenCalled();
  });

  it("invalidates ranking on preferences or unsaved earlier review changes", async () => {
    panel();
    await load(withEligibility);
    fireEvent.click(
      screen.getByRole("button", { name: "Preview readiness resume ranking" }),
    );
    await screen.findByRole("button", { name: "Review & select Platform" });
    fireEvent.change(screen.getByLabelText("Preferred resume tags"), {
      target: { value: "cloud" },
    });
    expect(
      screen.queryByRole("button", { name: "Review & select Platform" }),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Classification for passage 1"), {
      target: { value: "AMBIGUOUS" },
    });
    expect(
      screen.getByRole("button", { name: "Preview readiness resume ranking" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Preview evidence assessment" }),
    ).toBeDisabled();
  });

  it.each(["application", "profile", "disconnect"])(
    "ignores stale local load after %s change without automatic replacement requests",
    async (change) => {
      const old = deferred<JobReadinessSnapshot>();
      vi.mocked(api.getJobReadiness).mockReturnValueOnce(old.promise);
      const view = panel();
      fireEvent.click(
        screen.getByRole("button", { name: "Load saved job evidence" }),
      );
      view.rerender(
        <JobReadinessPanel
          backendReady={change !== "disconnect"}
          applicationId={change === "application" ? "app-2" : "app-1"}
          profileId={change === "profile" ? "profile-2" : "profile-1"}
          onChanged={changed}
        />,
      );
      await act(async () => old.resolve(snapshot));
      expect(screen.queryByText(/Review status:/)).not.toBeInTheDocument();
      expect(api.getJobReadiness).toHaveBeenCalledTimes(1);
    },
  );

  it("ignores an approval response after application changes", async () => {
    const old = deferred<JobReadinessSnapshot>();
    vi.mocked(api.approveJobRequirements).mockReturnValueOnce(old.promise);
    const view = panel();
    await load();
    fireEvent.click(
      screen.getByRole("button", { name: "Preview source requirements" }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review & approve requirements",
      }),
    );
    view.rerender(
      <JobReadinessPanel
        backendReady
        applicationId="app-2"
        profileId="profile-1"
        onChanged={changed}
      />,
    );
    await act(async () => old.resolve(withRequirements));
    expect(changed).not.toHaveBeenCalled();
    expect(
      screen.queryByText(/choice was saved locally/),
    ).not.toBeInTheDocument();
  });

  it("sanitizes failures, refuses mismatched application responses, and requires reload", async () => {
    panel();
    await load();
    vi.mocked(api.previewJobRequirements).mockResolvedValue({
      ...requirements,
      application_id: "wrong-app",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview source requirements" }),
    );
    await screen.findByRole("alert");
    expect(
      screen.queryByRole("button", { name: "Review & approve requirements" }),
    ).not.toBeInTheDocument();
    vi.mocked(api.getJobReadiness).mockRejectedValue(
      new Error("private provider payload"),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Load saved job evidence" }),
    );
    await screen.findByRole("alert");
    expect(screen.queryByText(/private provider/)).not.toBeInTheDocument();
    expect(api.approveJobRequirements).not.toHaveBeenCalled();
  });

  it("keeps unsupported workflows read-only and disconnected actions disabled", async () => {
    const view = panel();
    await load({
      ...snapshot,
      supported: false,
      status: "UNSUPPORTED",
      allowed_actions: [],
      source: null,
      spans: [],
    });
    expect(
      screen.queryByRole("button", { name: "Preview source requirements" }),
    ).not.toBeInTheDocument();
    view.rerender(
      <JobReadinessPanel
        backendReady={false}
        applicationId="app-1"
        profileId="profile-1"
        onChanged={changed}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Load saved job evidence" }),
    ).toBeDisabled();
  });
});
