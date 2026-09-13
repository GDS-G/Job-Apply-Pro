import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CommunicationMutationAudit,
  CommunicationRecord,
  OutboundDraft,
  WorkflowRunSnapshot,
} from "@job-apply-pro/contracts";

import { MailDraftPanel } from "./MailDraftPanel";

const record: CommunicationRecord = {
  id: "analysis-1",
  received_at: "2026-09-12T12:00:00Z",
  created_at: "2026-09-12T12:00:00Z",
  analysis: {
    message: {
      provider: "GMAIL",
      provider_message_id: "message-1",
      provider_thread_id: "thread-1",
      sender: "Recruiter <recruiter@example.invalid>",
      recipients: ["candidate@example.invalid"],
      subject: "Resume request",
      body_text: "Please send your resume.",
      received_at: "2026-09-12T12:00:00Z",
      attachment_names: [],
      referenced_identifiers: [],
      referenced_urls: [],
    },
    classification: {
      category: "RECRUITER_INQUIRY",
      confidence: 1,
      matched_signals: [],
      requires_review: true,
    },
    correlation: {
      workflow_id: "workflow-1",
      confidence: 1,
      matched_signals: [],
      requires_review: true,
    },
    reply_draft: {
      subject: "Re: Resume request",
      body_text: "Here is my reviewed resume.",
      category: "RECRUITER_INQUIRY",
      requires_review: true,
      auto_send_allowed: false,
      evidence: [],
    },
    proposed_times: [],
    time_proposal_requires_review: true,
  },
};
const workflow: WorkflowRunSnapshot = {
  workflow_id: "workflow-1",
  application_id: "application-1",
  profile_id: "profile-1",
  candidate_display_name: "Synthetic candidate",
  employer: "Fixture employer",
  title: "Fixture role",
  state: "DISCOVERED",
  progress: 0,
  updated_at: "2026-09-12T12:00:00Z",
  events: [],
};
const draft: OutboundDraft = {
  id: "draft-1",
  analysis_id: record.id,
  workflow_id: workflow.workflow_id,
  provider: "GMAIL",
  provider_thread_id: "thread-1",
  recipient: "recruiter@example.invalid",
  subject: "Re: Resume request",
  body_text: "Here is my reviewed resume.",
  category: "RECRUITER_INQUIRY",
  policy: "REVIEW_REQUIRED",
  document_version_ids: ["version-1"],
  fingerprint: "a".repeat(64),
  created_at: "2026-09-12T12:00:00Z",
  updated_at: "2026-09-12T12:00:00Z",
  attachment_manifest: {
    profile_id: "profile-1",
    policy_version: "mail-attachments-v1",
    attachments: [
      {
        document_version_id: "version-1",
        document_id: "document-1",
        file_name: "resume.pdf",
        media_type: "application/pdf",
        size_bytes: 1024,
        sha256: "b".repeat(64),
      },
    ],
  },
};
const audit: CommunicationMutationAudit = {
  id: "audit-1",
  kind: "SEND_MESSAGE",
  provider: "GMAIL",
  resource_id: "draft-1",
  idempotency_key: "native-main-key",
  fingerprint: draft.fingerprint,
  status: "ACCEPTED",
  confirmed_by: "desktop-user",
  provider_resource_id: "message-2",
  error_code: null,
  occurred_at: "2026-09-12T12:00:00Z",
};

describe("MailDraftPanel", () => {
  const api = window.jobApplyPro.workbench;
  beforeEach(() => {
    vi.spyOn(api, "listCommunicationDrafts").mockResolvedValue([draft]);
    vi.spyOn(api, "listCommunicationAudits").mockResolvedValue([]);
    vi.spyOn(api, "createCommunicationDraft").mockResolvedValue(draft);
    vi.spyOn(api, "sendCommunicationDraft").mockResolvedValue(audit);
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  function panel(backendReady = true) {
    return render(
      <MailDraftPanel
        backendReady={backendReady}
        records={[record]}
        workflows={[workflow]}
      />,
    );
  }
  async function selectDraft() {
    await waitFor(() =>
      expect(screen.getByLabelText("Saved mail draft")).not.toBeDisabled(),
    );
    fireEvent.change(screen.getByLabelText("Saved mail draft"), {
      target: { value: draft.id },
    });
  }
  async function selectSource() {
    await waitFor(() =>
      expect(screen.getByLabelText("Saved mail draft")).not.toBeDisabled(),
    );
    fireEvent.change(screen.getByLabelText("Reply to imported message"), {
      target: { value: record.id },
    });
  }
  it("loads only draft/audit metadata; no send or draft creation on mount", async () => {
    panel();
    await selectDraft();
    expect(
      screen.getByText(/certifications, education records and portfolios/),
    ).toHaveTextContent(
      "select an application workflow before attaching documents",
    );
    expect(screen.getByText("resume.pdf")).toBeInTheDocument();
    expect(screen.getByText("b".repeat(64))).toBeInTheDocument();
    expect(screen.getByText("version-1")).toBeInTheDocument();
    expect(screen.getByText(/1,024 bytes/)).toBeInTheDocument();
    expect(api.createCommunicationDraft).not.toHaveBeenCalled();
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it("creates a review-only reply with IDs, not bytes or renderer-authored manifest", async () => {
    panel();
    await selectSource();
    expect(screen.getByLabelText("Recipient email")).toHaveValue(
      "recruiter@example.invalid",
    );
    fireEvent.change(
      screen.getByLabelText("Immutable document version IDs (optional)"),
      { target: { value: "version-1" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Save reply for review" }),
    );
    await screen.findByText(/Draft saved for review only/);
    expect(api.createCommunicationDraft).toHaveBeenCalledExactlyOnceWith({
      analysis_id: "analysis-1",
      workflow_id: "workflow-1",
      provider: "GMAIL",
      provider_thread_id: "thread-1",
      recipient: "recruiter@example.invalid",
      subject: "Re: Resume request",
      body_text: "Here is my reviewed resume.",
      category: "RECRUITER_INQUIRY",
      policy: "REVIEW_REQUIRED",
      document_version_ids: ["version-1"],
    });
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it("requires an owning workflow and unique bounded version IDs", async () => {
    panel();
    await selectSource();
    const versionField = screen.getByLabelText(
      "Immutable document version IDs (optional)",
    );
    const save = screen.getByRole("button", { name: "Save reply for review" });
    for (const value of ["v1 v1", "v1 v2 v3 v4 v5", "../path"]) {
      fireEvent.change(versionField, { target: { value } });
      expect(save).toBeDisabled();
    }
    fireEvent.change(versionField, { target: { value: "version-1" } });
    fireEvent.change(
      screen.getByLabelText("Owning workflow (required for attachments)"),
      { target: { value: "" } },
    );
    expect(save).toBeDisabled();
    expect(api.createCommunicationDraft).not.toHaveBeenCalled();
  });
  it("sends only ID/fingerprint through native approval and reports acceptance, never delivery", async () => {
    panel();
    await selectDraft();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    );
    await waitFor(() =>
      expect(
        screen.getAllByText(
          /Provider accepted this send; delivery is not confirmed/,
        ).length,
      ).toBeGreaterThan(0),
    );
    expect(api.sendCommunicationDraft).toHaveBeenCalledExactlyOnceWith(
      "draft-1",
      draft.fingerprint,
    );
    expect(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    ).toBeDisabled();
  });
  it.each(["ACCEPTED", "UNCERTAIN", "PLANNED", "CONFIRMED", "FAILED"] as const)(
    "disables a previously %s draft even after reload",
    async (status) => {
      vi.mocked(api.listCommunicationAudits).mockResolvedValue([
        { ...audit, status },
      ]);
      panel();
      await selectDraft();
      expect(
        screen.getByRole("button", {
          name: "Review & send with native approval",
        }),
      ).toBeDisabled();
      expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
    },
  );
  it("handles native cancellation without claiming a send occurred or blocking later review", async () => {
    vi.mocked(api.sendCommunicationDraft).mockResolvedValue(null);
    panel();
    await selectDraft();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    );
    await screen.findByText("Native approval cancelled. No message was sent.");
    expect(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    ).not.toBeDisabled();
    expect(api.sendCommunicationDraft).toHaveBeenCalledTimes(1);
  });
  it("does not expose errors or automatically retry an ambiguous send", async () => {
    vi.mocked(api.sendCommunicationDraft).mockRejectedValue(
      new Error("private-token-and-provider-body"),
    );
    panel();
    await selectDraft();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    );
    await screen.findByRole("alert");
    expect(screen.getByRole("alert")).toHaveTextContent(
      /Inspect the provider account/,
    );
    expect(screen.queryByText(/private-token/)).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh mail drafts" }),
    );
    await waitFor(() =>
      expect(api.listCommunicationAudits).toHaveBeenCalledTimes(2),
    );
    expect(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    ).toBeDisabled();
    expect(api.sendCommunicationDraft).toHaveBeenCalledTimes(1);
  });
  it("blocks legacy attachment drafts without a verified manifest", async () => {
    vi.mocked(api.listCommunicationDrafts).mockResolvedValue([
      { ...draft, attachment_manifest: null },
    ]);
    panel();
    await selectDraft();
    expect(
      screen.getByText(/Legacy draft has no verified attachment manifest/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    ).toBeDisabled();
  });
  it("does not fetch or send while disconnected", () => {
    panel(false);
    expect(
      screen.getByRole("button", { name: "Save reply for review" }),
    ).toBeDisabled();
    expect(api.listCommunicationDrafts).not.toHaveBeenCalled();
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it("disables sending when audit loading fails and sanitizes the error", async () => {
    vi.mocked(api.listCommunicationAudits).mockRejectedValue(
      new Error("private audit payload"),
    );
    panel();
    await screen.findByRole("alert");
    expect(screen.getByLabelText("Saved mail draft")).toBeDisabled();
    expect(screen.queryByText(/private audit payload/)).not.toBeInTheDocument();
  });
});
