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
  MailReplyContext,
  OutboundDraft,
  WorkflowRunSnapshot,
} from "@job-apply-pro/contracts";

import { MailDraftPanel } from "./MailDraftPanel";

const context: MailReplyContext = {
  policy_version: "mail-reply-v1",
  provider: "GMAIL",
  account_key: "c".repeat(64),
  account_label: "candidate@example.invalid",
  connection_fingerprint: "d".repeat(64),
  source_record_id: "analysis-1",
  source_message_id: "message-1",
  source_thread_id: "thread-1",
  source_id_format: "GMAIL",
  recipient: "recruiter@example.invalid",
  subject: "Re: Resume request",
  rfc_message_id: "<original@example.invalid>",
  references: [],
  mime_reply_supported: true,
  fingerprint: "e".repeat(64),
};
const record: CommunicationRecord = {
  id: "analysis-1",
  reply_context: context,
  reply_unavailable_reason: null,
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
  mode: "REPLY",
  account_key: context.account_key,
  account_label: context.account_label,
  reply_context: context,
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

  function panel(backendReady = true, incomingRecords = [record]) {
    return render(
      <MailDraftPanel
        backendReady={backendReady}
        records={incomingRecords}
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
    fireEvent.change(screen.getByLabelText("Imported source message"), {
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
    expect(screen.getByLabelText("Recipient email")).toHaveAttribute(
      "readonly",
    );
    expect(screen.getByLabelText("Message subject")).toHaveAttribute(
      "readonly",
    );
    expect(screen.getByLabelText("Message mode")).toHaveValue("REPLY");
    fireEvent.change(
      screen.getByLabelText("Immutable document version IDs (optional)"),
      { target: { value: "version-1" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Save reply for review" }),
    );
    await screen.findByText(/Draft saved for review only/);
    expect(api.createCommunicationDraft).toHaveBeenCalledExactlyOnceWith({
      mode: "REPLY",
      analysis_id: "analysis-1",
      workflow_id: "workflow-1",
      source_fingerprint: context.fingerprint,
      body_text: "Here is my reviewed resume.",
      category: "RECRUITER_INQUIRY",
      policy: "REVIEW_REQUIRED",
      document_version_ids: ["version-1"],
    });
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it("uses the backend reply target, not the displayed sender or suggested subject", async () => {
    panel(true, [
      {
        ...record,
        analysis: {
          ...record.analysis,
          message: {
            ...record.analysis.message,
            sender: "Misleading <wrong@example.invalid>",
          },
          reply_draft: {
            ...record.analysis.reply_draft,
            subject: "Unbound suggestion",
          },
        },
      },
    ]);
    await selectSource();
    expect(screen.getByLabelText("Recipient email")).toHaveValue(
      context.recipient,
    );
    expect(screen.getByLabelText("Message subject")).toHaveValue(
      context.subject,
    );
    expect(api.createCommunicationDraft).not.toHaveBeenCalled();
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it("requires explicit standalone mode for editable recipient and subject, with no threading input", async () => {
    vi.mocked(api.createCommunicationDraft).mockResolvedValue({
      ...draft,
      mode: "NEW_MESSAGE",
      reply_context: null,
      provider_thread_id: "",
      recipient: "new@example.invalid",
      subject: "New conversation",
    });
    panel();
    await selectSource();
    fireEvent.change(screen.getByLabelText("Message mode"), {
      target: { value: "NEW_MESSAGE" },
    });
    expect(screen.getByLabelText("Recipient email")).not.toHaveAttribute(
      "readonly",
    );
    expect(screen.getByLabelText("Message subject")).not.toHaveAttribute(
      "readonly",
    );
    fireEvent.change(screen.getByLabelText("Recipient email"), {
      target: { value: "new@example.invalid" },
    });
    fireEvent.change(screen.getByLabelText("Message subject"), {
      target: { value: "New conversation" },
    });
    expect(api.createCommunicationDraft).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Save new message for review" }),
    );
    await screen.findByText(/Draft saved for review only/);
    expect(api.createCommunicationDraft).toHaveBeenCalledExactlyOnceWith({
      mode: "NEW_MESSAGE",
      analysis_id: record.id,
      workflow_id: "workflow-1",
      provider: "GMAIL",
      recipient: "new@example.invalid",
      subject: "New conversation",
      body_text: draft.body_text,
      policy: "REVIEW_REQUIRED",
      category: "RECRUITER_INQUIRY",
      document_version_ids: [],
    });
    expect(
      screen.getByText(/Mode: New standalone message/),
    ).toBeInTheDocument();
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Message mode"), {
      target: { value: "REPLY" },
    });
    expect(screen.getByLabelText("Saved mail draft")).toHaveValue("");
    expect(screen.getByLabelText("Recipient email")).toHaveValue(
      context.recipient,
    );
  });
  it("never guesses threading for an unavailable source or silently falls back to new-message mode", async () => {
    panel(true, [
      {
        ...record,
        reply_context: null,
        reply_unavailable_reason: "Missing immutable source",
      },
    ]);
    await selectSource();
    expect(
      screen.getByRole("button", { name: "Save reply for review" }),
    ).toBeDisabled();
    expect(screen.getByLabelText("Message mode")).toHaveValue("REPLY");
    expect(
      screen.getByText(/Threaded reply is unavailable/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Recipient email")).toHaveValue("");
    expect(api.createCommunicationDraft).not.toHaveBeenCalled();
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Message mode"), {
      target: { value: "NEW_MESSAGE" },
    });
    fireEvent.change(screen.getByLabelText("Recipient email"), {
      target: { value: "explicit@example.invalid" },
    });
    expect(
      screen.getByRole("button", { name: "Save new message for review" }),
    ).not.toBeDisabled();
  });
  it("saves an offline standalone preview but requires a fresh bound draft after connecting", async () => {
    const preview: OutboundDraft = {
      ...draft,
      mode: "NEW_MESSAGE",
      account_key: null,
      account_label: null,
      reply_context: null,
      provider_thread_id: "",
      document_version_ids: [],
      attachment_manifest: null,
    };
    vi.mocked(api.createCommunicationDraft).mockResolvedValueOnce(preview);
    const unboundRecord = {
      ...record,
      reply_context: null,
      reply_unavailable_reason: "No source account",
    };
    const view = panel(true, [unboundRecord]);
    await selectSource();
    fireEvent.change(screen.getByLabelText("Message mode"), {
      target: { value: "NEW_MESSAGE" },
    });
    fireEvent.change(screen.getByLabelText("Recipient email"), {
      target: { value: context.recipient },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save new message for review" }),
    );
    await screen.findByText(/Offline standalone preview saved locally/);
    expect(
      screen.getByText(/Offline preview — not send-ready/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    ).toBeDisabled();
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();

    view.rerender(
      <MailDraftPanel backendReady records={[record]} workflows={[workflow]} />,
    );
    expect(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    ).toBeDisabled();
    vi.mocked(api.listCommunicationDrafts).mockResolvedValueOnce([preview]);
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh mail drafts" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Saved mail draft")).not.toBeDisabled(),
    );
    expect(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    ).toBeDisabled();
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
    expect(api.createCommunicationDraft).toHaveBeenCalledTimes(1);

    fireEvent.click(
      screen.getByRole("button", { name: "Reload source context" }),
    );
    const fresh = {
      ...preview,
      id: "fresh-bound-draft",
      account_key: context.account_key,
      account_label: context.account_label,
    };
    vi.mocked(api.createCommunicationDraft).mockResolvedValueOnce(fresh);
    fireEvent.click(
      screen.getByRole("button", { name: "Save new message for review" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Saved mail draft")).toHaveValue(fresh.id),
    );
    expect(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    ).not.toBeDisabled();
    expect(api.createCommunicationDraft).toHaveBeenCalledTimes(2);
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it("preserves an empty verified reply subject", async () => {
    panel(true, [{ ...record, reply_context: { ...context, subject: "" } }]);
    await selectSource();
    expect(screen.getByLabelText("Message subject")).toHaveValue("");
    expect(
      screen.getByRole("button", { name: "Save reply for review" }),
    ).not.toBeDisabled();
  });
  it.each([
    {
      reply_context: {
        ...context,
        account_key: "f".repeat(64),
        account_label: "other@example.invalid",
        fingerprint: "f".repeat(64),
      },
    },
    { reply_context: { ...context, connection_fingerprint: "f".repeat(64) } },
    { reply_context: { ...context, fingerprint: "f".repeat(64) } },
    { reply_context: null, reply_unavailable_reason: "Source unavailable" },
  ])(
    "invalidates preparation after source or account context changes without auto calls (%#)",
    async (change) => {
      const view = panel();
      await selectSource();
      view.rerender(
        <MailDraftPanel
          backendReady
          records={[{ ...record, ...change }]}
          workflows={[workflow]}
        />,
      );
      expect(
        screen.getByRole("button", { name: "Save reply for review" }),
      ).toBeDisabled();
      expect(
        screen.getByText(/Source or sending-account context changed\./),
      ).toBeInTheDocument();
      expect(api.createCommunicationDraft).not.toHaveBeenCalled();
      expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
      expect(api.listCommunicationDrafts).toHaveBeenCalledTimes(1);
      fireEvent.click(
        screen.getByRole("button", { name: "Reload source context" }),
      );
      if (change.reply_context) {
        fireEvent.click(
          screen.getByRole("button", { name: "Save reply for review" }),
        );
        await waitFor(() =>
          expect(api.createCommunicationDraft).toHaveBeenCalledTimes(1),
        );
        expect(api.createCommunicationDraft).toHaveBeenCalledWith(
          expect.objectContaining({
            source_fingerprint: change.reply_context.fingerprint,
          }),
        );
      } else {
        expect(
          screen.getByRole("button", { name: "Save reply for review" }),
        ).toBeDisabled();
      }
    },
  );
  it("does not select a late prepared draft after its source/account context changed", async () => {
    let finish!: (value: OutboundDraft) => void;
    vi.mocked(api.createCommunicationDraft).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const view = panel();
    await selectSource();
    fireEvent.click(
      screen.getByRole("button", { name: "Save reply for review" }),
    );
    view.rerender(
      <MailDraftPanel
        backendReady
        records={[
          {
            ...record,
            reply_context: {
              ...context,
              connection_fingerprint: "f".repeat(64),
            },
          },
        ]}
        workflows={[workflow]}
      />,
    );
    finish(draft);
    await screen.findByText(/context changed during preparation/);
    expect(screen.getByLabelText("Saved mail draft")).toHaveValue("");
    expect(api.createCommunicationDraft).toHaveBeenCalledTimes(1);
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it("renders remote source context as plain text, without links or resources", async () => {
    const unsafeSubject = '<img src="https://example.invalid/track">';
    const view = panel(true, [
      {
        ...record,
        reply_context: {
          ...context,
          subject: unsafeSubject,
          source_message_id: "<script>remote()</script>",
        },
        analysis: {
          ...record.analysis,
          message: {
            ...record.analysis.message,
            provider_message_id: "<script>remote()</script>",
          },
        },
      },
    ]);
    await selectSource();
    expect(screen.getByLabelText("Message subject")).toHaveValue(unsafeSubject);
    expect(screen.getByText("<script>remote()</script>")).toBeInTheDocument();
    expect(view.container.querySelector("img,script,iframe,a")).toBeNull();
    expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it.each([
    { mode: null },
    { account_key: null },
    { account_label: null },
    { reply_context: null },
    { mode: "NEW_MESSAGE" as const, reply_context: null },
  ])(
    "blocks legacy or incomplete saved mode/account/reply bindings (%#)",
    async (change) => {
      vi.mocked(api.listCommunicationDrafts).mockResolvedValue([
        { ...draft, ...change },
      ]);
      panel();
      await selectDraft();
      expect(
        screen.getByText(
          /no valid explicit mode or immutable account\/reply binding/,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", {
          name: "Review & send with native approval",
        }),
      ).toBeDisabled();
      expect(api.sendCommunicationDraft).not.toHaveBeenCalled();
    },
  );
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
  it("requires a successful refresh after a proven pre-dispatch failure before another user review", async () => {
    vi.mocked(api.sendCommunicationDraft).mockResolvedValueOnce({
      outcome: "NOT_DISPATCHED",
      reason: "REVIEW_UNAVAILABLE",
    });
    panel();
    await selectDraft();
    const send = screen.getByRole("button", {
      name: "Review & send with native approval",
    });
    fireEvent.click(send);
    await screen.findByText(
      "No send was dispatched by this review. Refresh mail drafts and review again.",
    );
    expect(send).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/result is unresolved/)).not.toBeInTheDocument();
    expect(screen.queryByText(/outcome is uncertain/)).not.toBeInTheDocument();
    expect(api.sendCommunicationDraft).toHaveBeenCalledTimes(1);
    expect(api.listCommunicationDrafts).toHaveBeenCalledTimes(1);
    expect(api.listCommunicationAudits).toHaveBeenCalledTimes(1);

    const refreshed = { ...draft, fingerprint: "c".repeat(64) };
    vi.mocked(api.listCommunicationDrafts).mockResolvedValue([refreshed]);
    vi.mocked(api.listCommunicationAudits).mockRejectedValueOnce(
      new Error("private preflight audit error"),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh mail drafts" }),
    );
    await screen.findByRole("alert");
    expect(send).toBeDisabled();
    expect(screen.queryByText(/private preflight/)).not.toBeInTheDocument();
    expect(api.sendCommunicationDraft).toHaveBeenCalledTimes(1);

    fireEvent.click(
      screen.getByRole("button", { name: "Refresh mail drafts" }),
    );
    await waitFor(() => expect(send).not.toBeDisabled());
    expect(screen.queryByText(/result is unresolved/)).not.toBeInTheDocument();
    expect(api.sendCommunicationDraft).toHaveBeenCalledTimes(1);
    vi.mocked(api.sendCommunicationDraft).mockResolvedValueOnce({
      ...audit,
      fingerprint: refreshed.fingerprint,
    });
    fireEvent.click(send);
    await waitFor(() =>
      expect(api.sendCommunicationDraft).toHaveBeenCalledTimes(2),
    );
    expect(api.sendCommunicationDraft).toHaveBeenLastCalledWith(
      draft.id,
      refreshed.fingerprint,
    );
    expect(api.createCommunicationDraft).not.toHaveBeenCalled();
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
    await waitFor(() =>
      expect(screen.getByLabelText("Saved mail draft")).not.toBeDisabled(),
    );
    expect(
      screen.getByRole("button", {
        name: "Review & send with native approval",
      }),
    ).toBeDisabled();
    expect(api.sendCommunicationDraft).toHaveBeenCalledTimes(1);
  });
  it("keeps a returned uncertain audit blocked after refresh without retrying", async () => {
    vi.mocked(api.sendCommunicationDraft).mockResolvedValue({
      ...audit,
      status: "UNCERTAIN",
      provider_resource_id: null,
    });
    panel();
    await selectDraft();
    const send = screen.getByRole("button", {
      name: "Review & send with native approval",
    });
    fireEvent.click(send);
    await screen.findAllByText(/Send outcome is uncertain/);
    expect(send).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh mail drafts" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Saved mail draft")).not.toBeDisabled(),
    );
    expect(send).toBeDisabled();
    expect(screen.getByText(/result is unresolved/)).toBeInTheDocument();
    expect(api.sendCommunicationDraft).toHaveBeenCalledTimes(1);
    expect(api.createCommunicationDraft).not.toHaveBeenCalled();
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
