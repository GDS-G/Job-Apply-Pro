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
  GreenhouseImportResult,
  GreenhouseJobList,
  GreenhouseJobReview,
  WorkflowRunSnapshot,
} from "@job-apply-pro/contracts";

import { GreenhouseDiscoveryPanel } from "./GreenhouseDiscoveryPanel";

const review: GreenhouseJobReview = {
  board_token: "ExampleBoard",
  posting_id: "1234",
  title: "Platform Engineer",
  employer: "Example Employer",
  location: "Remote",
  source_url: null,
  navigation_supported: false,
  description:
    '<script>untrusted()</script>\n<img src="https://employer.invalid/pixel">',
  api_url: "https://boards-api.greenhouse.io/v1/boards/ExampleBoard/jobs/1234",
  reported_url: "https://employer.invalid/apply/1234",
  provider_updated_at: "2026-09-15T10:00:00Z",
  fetched_at: "2026-09-15T10:01:00Z",
  normalizer_version: "greenhouse-v1",
  review_fingerprint: "a".repeat(64),
  qualification_status: "NOT_EVALUATED",
};
const listing: GreenhouseJobList = {
  board_token: review.board_token,
  board_name: "Example public board",
  fetched_at: review.fetched_at,
  jobs: [review, { ...review, posting_id: "5678", title: "Security Engineer" }],
  excluded_prospect_count: 1,
};
const workflow: WorkflowRunSnapshot = {
  workflow_id: "discovery-workflow",
  application_id: "local-application",
  profile_id: "profile-1",
  candidate_display_name: "Synthetic candidate",
  employer: review.employer,
  title: review.title,
  state: "DISCOVERED",
  progress: 5,
  updated_at: review.fetched_at,
  events: [],
  allowed_controls: [],
};
const imported: GreenhouseImportResult = {
  outcome: "IMPORTED",
  job: {
    id: "job-1",
    source: "greenhouse",
    external_id: "ExampleBoard:1234",
    employer: review.employer,
    title: review.title,
    location: review.location,
    source_url: null,
    description_hash: "b".repeat(64),
    discovered_at: review.fetched_at,
  },
  workflow,
  notice: "Synthetic local result",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("GreenhouseDiscoveryPanel", () => {
  const api = window.jobApplyPro.workbench;
  const onImported = vi.fn<(value: WorkflowRunSnapshot) => Promise<void>>();

  beforeEach(() => {
    vi.spyOn(api, "listGreenhouseJobs").mockResolvedValue(listing);
    vi.spyOn(api, "reviewGreenhouseJob").mockResolvedValue(review);
    vi.spyOn(api, "importGreenhouseJob").mockResolvedValue(imported);
    onImported.mockReset().mockResolvedValue(undefined);
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  function panel(profileId: string | null = "profile-1", backendReady = true) {
    return render(
      <GreenhouseDiscoveryPanel
        backendReady={backendReady}
        profileId={profileId}
        onImported={onImported}
      />,
    );
  }
  async function listJobs() {
    fireEvent.change(screen.getByLabelText("Greenhouse board token"), {
      target: { value: review.board_token },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview public jobs" }),
    );
    await screen.findByLabelText("Public job to review");
  }
  async function reviewJob() {
    await listJobs();
    fireEvent.change(screen.getByLabelText("Public job to review"), {
      target: { value: review.posting_id },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected job" }),
    );
    await screen.findByRole("button", { name: "Import reviewed job locally" });
  }

  it("does not fetch on mount, typing, selection, or profile changes", async () => {
    const view = panel();
    expect(api.listGreenhouseJobs).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Greenhouse board token"), {
      target: { value: review.board_token },
    });
    expect(api.listGreenhouseJobs).not.toHaveBeenCalled();
    await listJobs();
    fireEvent.change(screen.getByLabelText("Public job to review"), {
      target: { value: review.posting_id },
    });
    expect(api.reviewGreenhouseJob).not.toHaveBeenCalled();
    view.rerender(
      <GreenhouseDiscoveryPanel
        backendReady
        profileId="profile-2"
        onImported={onImported}
      />,
    );
    expect(api.listGreenhouseJobs).toHaveBeenCalledTimes(1);
    expect(api.reviewGreenhouseJob).not.toHaveBeenCalled();
    expect(api.importGreenhouseJob).not.toHaveBeenCalled();
  });

  it.each([
    "",
    "internal",
    "InTeRnAl",
    "https://example.invalid",
    "../board",
    " leading",
    "bad token",
  ])("does not submit an invalid or reserved board token (%s)", (token) => {
    panel();
    fireEvent.change(screen.getByLabelText("Greenhouse board token"), {
      target: { value: token },
    });
    const button = screen.getByRole("button", { name: "Preview public jobs" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(api.listGreenhouseJobs).not.toHaveBeenCalled();
  });

  it("reviews exact plain text and imports only the selected backend fingerprint", async () => {
    const view = panel();
    await reviewJob();
    expect(api.listGreenhouseJobs).toHaveBeenCalledExactlyOnceWith({
      board_token: "ExampleBoard",
    });
    expect(api.reviewGreenhouseJob).toHaveBeenCalledExactlyOnceWith({
      board_token: "ExampleBoard",
      posting_id: "1234",
    });
    expect(api.importGreenhouseJob).not.toHaveBeenCalled();
    expect(view.container.querySelector("pre")?.textContent).toBe(
      review.description,
    );
    expect(view.container.querySelector("script, img, iframe, a")).toBeNull();
    expect(
      screen.getByText(/Custom or unsupported destination/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Qualification: not evaluated/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/1 prospect postings excluded/),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Import reviewed job locally" }),
    );
    await screen.findByText(/Job imported into your local workflow queue/);
    expect(api.importGreenhouseJob).toHaveBeenCalledExactlyOnceWith({
      board_token: "ExampleBoard",
      posting_id: "1234",
      review_fingerprint: review.review_fingerprint,
      profile_id: "profile-1",
    });
    expect(onImported).toHaveBeenCalledExactlyOnceWith(workflow);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Review selected job" }),
      ).not.toBeDisabled(),
    );
    expect(
      screen.getByRole("button", { name: "Import reviewed job locally" }),
    ).toBeDisabled();
  });

  it("reuses an existing local workflow without claiming a new submission", async () => {
    vi.mocked(api.importGreenhouseJob).mockResolvedValue({
      ...imported,
      outcome: "EXISTING",
    });
    panel();
    await reviewJob();
    fireEvent.click(
      screen.getByRole("button", { name: "Import reviewed job locally" }),
    );
    await screen.findByText(
      /existing workflow was reused; no application was submitted/,
    );
    expect(onImported).toHaveBeenCalledExactlyOnceWith(workflow);
  });

  it("invalidates a completed review when the candidate profile changes", async () => {
    const view = panel();
    await reviewJob();
    view.rerender(
      <GreenhouseDiscoveryPanel
        backendReady
        profileId="profile-2"
        onImported={onImported}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Import reviewed job locally" }),
    ).not.toBeInTheDocument();
    expect(api.reviewGreenhouseJob).toHaveBeenCalledTimes(1);
    expect(api.importGreenhouseJob).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected job" }),
    );
    const button = await screen.findByRole("button", {
      name: "Import reviewed job locally",
    });
    vi.mocked(api.importGreenhouseJob).mockResolvedValue({
      ...imported,
      workflow: { ...workflow, profile_id: "profile-2" },
    });
    fireEvent.click(button);
    await waitFor(() =>
      expect(api.importGreenhouseJob).toHaveBeenCalledTimes(1),
    );
    expect(api.importGreenhouseJob).toHaveBeenCalledWith(
      expect.objectContaining({ profile_id: "profile-2" }),
    );
  });

  it("permits public review without a profile but never imports it", async () => {
    panel(null);
    await reviewJob();
    expect(
      screen.getByRole("button", { name: "Import reviewed job locally" }),
    ).toBeDisabled();
    expect(api.importGreenhouseJob).not.toHaveBeenCalled();
  });

  it("ignores an older list response after the user changes the board", async () => {
    const old = deferred<GreenhouseJobList>();
    vi.mocked(api.listGreenhouseJobs).mockReturnValueOnce(old.promise);
    panel();
    fireEvent.change(screen.getByLabelText("Greenhouse board token"), {
      target: { value: "OldBoard" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview public jobs" }),
    );
    fireEvent.change(screen.getByLabelText("Greenhouse board token"), {
      target: { value: review.board_token },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview public jobs" }),
    );
    await screen.findByText(listing.board_name);
    await act(async () =>
      old.resolve({
        ...listing,
        board_token: "OldBoard",
        board_name: "Stale board",
      }),
    );
    expect(screen.queryByText("Stale board")).not.toBeInTheDocument();
    expect(screen.getByText(listing.board_name)).toBeInTheDocument();
    expect(api.listGreenhouseJobs).toHaveBeenCalledTimes(2);
  });

  it("ignores a review response after a different posting is selected", async () => {
    const old = deferred<GreenhouseJobReview>();
    vi.mocked(api.reviewGreenhouseJob).mockReturnValueOnce(old.promise);
    panel();
    await listJobs();
    fireEvent.change(screen.getByLabelText("Public job to review"), {
      target: { value: "1234" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected job" }),
    );
    fireEvent.change(screen.getByLabelText("Public job to review"), {
      target: { value: "5678" },
    });
    await act(async () => old.resolve(review));
    expect(
      screen.queryByRole("button", { name: "Import reviewed job locally" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Public job to review")).toHaveValue("5678");
    expect(api.importGreenhouseJob).not.toHaveBeenCalled();
  });

  it("ignores an in-flight review when the candidate profile changes", async () => {
    const old = deferred<GreenhouseJobReview>();
    vi.mocked(api.reviewGreenhouseJob).mockReturnValueOnce(old.promise);
    const view = panel();
    await listJobs();
    fireEvent.change(screen.getByLabelText("Public job to review"), {
      target: { value: "1234" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected job" }),
    );
    view.rerender(
      <GreenhouseDiscoveryPanel
        backendReady
        profileId="profile-2"
        onImported={onImported}
      />,
    );
    await act(async () => old.resolve(review));
    expect(
      screen.queryByRole("button", { name: "Import reviewed job locally" }),
    ).not.toBeInTheDocument();
    expect(api.reviewGreenhouseJob).toHaveBeenCalledTimes(1);
  });

  it("requires another explicit review for STALE_REVIEW, without automatic requests", async () => {
    vi.mocked(api.importGreenhouseJob).mockResolvedValueOnce({
      outcome: "STALE_REVIEW",
      job: null,
      workflow: null,
      notice: "Changed",
    });
    panel();
    await reviewJob();
    fireEvent.click(
      screen.getByRole("button", { name: "Import reviewed job locally" }),
    );
    await screen.findByText(/posting changed since this review/);
    expect(
      screen.queryByRole("button", { name: "Import reviewed job locally" }),
    ).not.toBeInTheDocument();
    expect(api.reviewGreenhouseJob).toHaveBeenCalledTimes(1);
    expect(onImported).not.toHaveBeenCalled();
    const updated = { ...review, review_fingerprint: "c".repeat(64) };
    vi.mocked(api.reviewGreenhouseJob).mockResolvedValue(updated);
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected job" }),
    );
    const button = await screen.findByRole("button", {
      name: "Import reviewed job locally",
    });
    fireEvent.click(button);
    await waitFor(() =>
      expect(api.importGreenhouseJob).toHaveBeenCalledTimes(2),
    );
    expect(api.importGreenhouseJob).toHaveBeenLastCalledWith(
      expect.objectContaining({
        review_fingerprint: updated.review_fingerprint,
      }),
    );
  });

  it("does not present another review as a cure for SOURCE_CHANGED", async () => {
    vi.mocked(api.importGreenhouseJob).mockResolvedValue({
      outcome: "SOURCE_CHANGED",
      job: null,
      workflow: null,
      notice: "Changed snapshot",
    });
    panel();
    await reviewJob();
    fireEvent.click(
      screen.getByRole("button", { name: "Import reviewed job locally" }),
    );
    await screen.findByText(/another review will not replace it/);
    expect(
      screen.getByRole("button", { name: "Import reviewed job locally" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected job" }),
    );
    await waitFor(() =>
      expect(api.reviewGreenhouseJob).toHaveBeenCalledTimes(2),
    );
    expect(
      await screen.findByRole("button", {
        name: "Import reviewed job locally",
      }),
    ).toBeDisabled();
    expect(api.importGreenhouseJob).toHaveBeenCalledTimes(1);
    expect(onImported).not.toHaveBeenCalled();
  });

  it("clears unavailable sources without claiming an import", async () => {
    vi.mocked(api.importGreenhouseJob).mockResolvedValue({
      outcome: "SOURCE_UNAVAILABLE",
      job: null,
      workflow: null,
      notice: "Unavailable",
    });
    panel();
    await reviewJob();
    fireEvent.click(
      screen.getByRole("button", { name: "Import reviewed job locally" }),
    );
    await screen.findByText(/source job is unavailable/);
    expect(
      screen.queryByLabelText("Public job to review"),
    ).not.toBeInTheDocument();
    expect(onImported).not.toHaveBeenCalled();
    expect(api.listGreenhouseJobs).toHaveBeenCalledTimes(1);
  });

  it("sanitizes failed list/review/import requests and never retries automatically", async () => {
    vi.mocked(api.listGreenhouseJobs).mockRejectedValueOnce(
      new Error("private provider list details"),
    );
    panel();
    fireEvent.change(screen.getByLabelText("Greenhouse board token"), {
      target: { value: review.board_token },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview public jobs" }),
    );
    await screen.findByRole("alert");
    expect(screen.queryByText(/private provider/)).not.toBeInTheDocument();
    await listJobs();
    fireEvent.change(screen.getByLabelText("Public job to review"), {
      target: { value: "1234" },
    });
    vi.mocked(api.reviewGreenhouseJob).mockRejectedValueOnce(
      new Error("private provider review details"),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected job" }),
    );
    await screen.findByRole("alert");
    expect(screen.queryByText(/private provider/)).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Review selected job" }),
    );
    const button = await screen.findByRole("button", {
      name: "Import reviewed job locally",
    });
    vi.mocked(api.importGreenhouseJob).mockRejectedValueOnce(
      new Error("private provider import details"),
    );
    fireEvent.click(button);
    await screen.findByText(/local import result could not be confirmed/);
    expect(screen.queryByText(/private provider/)).not.toBeInTheDocument();
    expect(api.importGreenhouseJob).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    expect(onImported).not.toHaveBeenCalled();
  });

  it("ignores an import response after the profile changes instead of selecting the old workflow", async () => {
    const old = deferred<GreenhouseImportResult>();
    vi.mocked(api.importGreenhouseJob).mockReturnValueOnce(old.promise);
    const view = panel();
    await reviewJob();
    fireEvent.click(
      screen.getByRole("button", { name: "Import reviewed job locally" }),
    );
    view.rerender(
      <GreenhouseDiscoveryPanel
        backendReady
        profileId="profile-2"
        onImported={onImported}
      />,
    );
    await act(async () => old.resolve(imported));
    expect(onImported).not.toHaveBeenCalled();
    expect(
      screen.queryByText(/Job imported into your local workflow queue/),
    ).not.toBeInTheDocument();
  });

  it("does not enable any remote action while disconnected", () => {
    panel("profile-1", false);
    expect(screen.getByLabelText("Greenhouse board token")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Preview public jobs" }),
    ).toBeDisabled();
    expect(api.listGreenhouseJobs).not.toHaveBeenCalled();
    expect(api.reviewGreenhouseJob).not.toHaveBeenCalled();
    expect(api.importGreenhouseJob).not.toHaveBeenCalled();
  });
});
