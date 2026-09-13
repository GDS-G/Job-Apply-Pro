import type { IpcMainInvokeEvent } from "electron";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CommunicationDraftCreate,
  CommunicationMutationAudit,
  MailReplyContext,
  OutboundDraft,
} from "@job-apply-pro/contracts";

import { BackendClient } from "./backend-client.js";
import { registerMailDraftIpc } from "./mail-draft-ipc.js";

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

const context: MailReplyContext = {
  policy_version: "mail-reply-v1",
  provider: "GMAIL",
  account_key: "c".repeat(64),
  account_label: "candidate@example.invalid",
  connection_fingerprint: "d".repeat(64),
  source_record_id: "analysis-1",
  source_message_id: "message/opaque+1=",
  source_thread_id: "thread-1",
  source_id_format: "GMAIL",
  recipient: "recruiter@example.invalid",
  subject: "Reviewed reply",
  rfc_message_id: "<original@example.invalid>",
  references: ["<earlier@example.invalid>"],
  mime_reply_supported: true,
  fingerprint: "e".repeat(64),
};
const create: CommunicationDraftCreate = {
  mode: "REPLY",
  analysis_id: "analysis-1",
  workflow_id: "workflow-1",
  source_fingerprint: context.fingerprint,
  body_text: "Hello,\nPlease review the attached resume.",
  category: "RECRUITER_INQUIRY",
  policy: "REVIEW_REQUIRED",
  document_version_ids: ["version-1"],
};
const newMessage: CommunicationDraftCreate = {
  mode: "NEW_MESSAGE",
  analysis_id: create.analysis_id,
  workflow_id: create.workflow_id,
  body_text: create.body_text,
  category: create.category,
  policy: "REVIEW_REQUIRED",
  document_version_ids: create.document_version_ids,
  provider: "GMAIL",
  recipient: "other@example.invalid",
  subject: "A new conversation",
};
const draft: OutboundDraft = {
  mode: "REPLY",
  analysis_id: create.analysis_id,
  provider: "GMAIL",
  provider_thread_id: context.source_thread_id,
  recipient: context.recipient,
  subject: context.subject,
  body_text: create.body_text,
  category: create.category,
  document_version_ids: create.document_version_ids,
  reply_context: context,
  account_key: context.account_key,
  account_label: context.account_label,
  id: "draft-1",
  workflow_id: "workflow-1",
  policy: "REVIEW_REQUIRED",
  fingerprint: "a".repeat(64),
  created_at: "2026-09-12T12:00:00Z",
  updated_at: "2026-09-12T12:00:00Z",
  attachment_manifest: {
    profile_id: "profile-1",
    policy_version: "mail-attachments-v1",
    attachments: [
      {
        document_id: "document-1",
        document_version_id: "version-1",
        file_name: "resume.pdf",
        media_type: "application/pdf",
        sha256: "b".repeat(64),
        size_bytes: 1024,
      },
    ],
  },
};
const accepted: CommunicationMutationAudit = {
  id: "audit-1",
  kind: "SEND_MESSAGE",
  provider: "GMAIL",
  resource_id: draft.id,
  idempotency_key: "backend-idempotency",
  fingerprint: draft.fingerprint,
  status: "ACCEPTED",
  confirmed_by: "desktop-user",
  provider_resource_id: "provider-message-1",
  error_code: null,
  occurred_at: "2026-09-12T12:00:00Z",
};
const notDispatched = {
  outcome: "NOT_DISPATCHED",
  reason: "REVIEW_UNAVAILABLE",
} as const;

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("mail draft fixed HTTP routes", () => {
  const fetchMock = vi.fn<typeof fetch>();
  let client: BackendClient;
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockImplementation(async () => Response.json(draft));
    vi.stubGlobal("fetch", fetchMock);
    client = new BackendClient("http://127.0.0.1:8765", "test-token");
  });
  it("uses fixed authenticated list, exact draft, create, audit and send routes", async () => {
    await client.listCommunicationDrafts();
    await client.getCommunicationDraft("draft/with?untrusted#segments");
    await client.createCommunicationDraft(create);
    await client.listCommunicationAudits();
    const confirmation = {
      fingerprint: draft.fingerprint,
      idempotency_key: "new-key-123",
      confirmed_by: "desktop-user" as const,
    };
    await client.sendCommunicationDraft(draft.id, confirmation);
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "http://127.0.0.1:8765/communications/drafts",
      "http://127.0.0.1:8765/communications/drafts/draft%2Fwith%3Funtrusted%23segments",
      "http://127.0.0.1:8765/communications/drafts",
      "http://127.0.0.1:8765/communications/mutation-audits",
      "http://127.0.0.1:8765/communications/drafts/draft-1/send",
    ]);
    expect(fetchMock.mock.calls[2]?.[1]?.body).toBe(JSON.stringify(create));
    expect(fetchMock.mock.calls[4]?.[1]?.body).toBe(
      JSON.stringify(confirmation),
    );
    for (const [, options] of fetchMock.mock.calls)
      expect(options?.headers).toMatchObject({
        "X-Job-Apply-Pro-Token": "test-token",
      });
  });
});

describe("mail IPC native approval boundary", () => {
  const client = {
    listCommunicationDrafts: vi.fn<BackendClient["listCommunicationDrafts"]>(),
    getCommunicationDraft: vi.fn<BackendClient["getCommunicationDraft"]>(),
    createCommunicationDraft:
      vi.fn<BackendClient["createCommunicationDraft"]>(),
    listCommunicationAudits: vi.fn<BackendClient["listCommunicationAudits"]>(),
    sendCommunicationDraft: vi.fn<BackendClient["sendCommunicationDraft"]>(),
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
    client.listCommunicationDrafts.mockResolvedValue([draft]);
    client.getCommunicationDraft.mockResolvedValue(draft);
    client.createCommunicationDraft.mockResolvedValue(draft);
    client.listCommunicationAudits.mockResolvedValue([]);
    client.sendCommunicationDraft.mockResolvedValue(accepted);
    showMessageBox.mockResolvedValue({ response: 1 });
    fromWebContents.mockReturnValue(undefined);
    registerMailDraftIpc(client as unknown as BackendClient);
  });
  it("registers only four explicit channels and read-only listing accepts no arguments", async () => {
    expect([...handlers.keys()]).toEqual([
      "communications:drafts-list",
      "communications:audits-list",
      "communications:draft-create",
      "communications:draft-send",
    ]);
    await invoke("communications:drafts-list");
    await invoke("communications:audits-list");
    for (const channel of [
      "communications:drafts-list",
      "communications:audits-list",
    ]) {
      await expect(invoke(channel, undefined)).rejects.toThrow(TypeError);
      await expect(invoke(channel, { path: "/send" })).rejects.toThrow(
        TypeError,
      );
    }
    expect(client.listCommunicationDrafts).toHaveBeenCalledTimes(1);
    expect(client.listCommunicationAudits).toHaveBeenCalledTimes(1);
  });
  it("creates only review-required metadata, never document bytes", async () => {
    await expect(invoke("communications:draft-create", create)).resolves.toBe(
      draft,
    );
    expect(client.createCommunicationDraft).toHaveBeenCalledExactlyOnceWith(
      create,
    );
    expect(client.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it("creates an explicit standalone message without threading or source fingerprint", async () => {
    await invoke("communications:draft-create", newMessage);
    expect(client.createCommunicationDraft).toHaveBeenCalledExactlyOnceWith(
      newMessage,
    );
    expect(client.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it("sanitizes backend draft preparation failures without requesting a send", async () => {
    client.createCommunicationDraft.mockRejectedValueOnce(
      new Error("private source account headers"),
    );
    await expect(invoke("communications:draft-create", create)).rejects.toThrow(
      "Mail draft could not be prepared. Refresh the source and review again. No send was requested.",
    );
    expect(client.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it.each([
    null,
    [],
    {},
    { ...create, bytes: "secret document" },
    { ...create, attachment_manifest: draft.attachment_manifest },
    { ...create, policy: "AUTOMATIC" },
    { ...create, provider: "GOOGLE_CALENDAR" },
    { ...create, category: "OTHER" },
    { ...create, recipient: "a@example.invalid,b@example.invalid" },
    { ...create, subject: "header\r\nBcc: a@example.invalid" },
    { ...create, body_text: "hello\u0000world" },
    { ...create, analysis_id: "../draft" },
    { ...create, workflow_id: null },
    { ...create, document_version_ids: ["duplicate", "duplicate"] },
    { ...create, document_version_ids: ["a", "b", "c", "d", "e"] },
    { ...create, document_version_ids: [42] },
    ...[
      "provider",
      "provider_thread_id",
      "recipient",
      "subject",
      "headers",
      "account_key",
      "account_label",
      "reply_context",
      "rfc_message_id",
      "references",
    ].map((key) => ({ ...create, [key]: "override" })),
    { ...create, mode: undefined },
    { ...create, source_fingerprint: "a".repeat(64) + "\n" },
    { ...create, source_fingerprint: undefined },
    { ...create, policy: undefined },
    { ...create, workflow_id: undefined },
    { ...newMessage, source_fingerprint: context.fingerprint },
    { ...newMessage, provider_thread_id: "" },
    { ...newMessage, reply_context: null },
    { ...newMessage, recipient: "a..b@example.invalid" },
    { ...newMessage, recipient: "用户@example.invalid" },
    { ...newMessage, recipient: "a@-example.invalid" },
    { ...newMessage, subject: "" },
    { ...newMessage, subject: "bad\r\nBcc: victim@example.invalid" },
  ])(
    "rejects malformed or expanded draft input before backend dispatch (%#)",
    async (value) => {
      await expect(
        invoke("communications:draft-create", value),
      ).rejects.toThrow(TypeError);
      expect(client.createCommunicationDraft).not.toHaveBeenCalled();
    },
  );
  it("loads the authoritative draft twice, shows exact metadata, sends with main-owned identity/key", async () => {
    await expect(
      invoke("communications:draft-send", draft.id, draft.fingerprint),
    ).resolves.toBe(accepted);
    expect(client.getCommunicationDraft).toHaveBeenCalledTimes(2);
    const options = showMessageBox.mock.calls[0]?.[0];
    expect(options).toMatchObject({
      defaultId: 0,
      cancelId: 0,
      buttons: ["Cancel", "Send reviewed email"],
    });
    for (const expected of [
      "REPLY — source-bound reply",
      context.source_record_id,
      context.source_message_id,
      context.source_thread_id,
      context.account_key,
      context.account_label,
      context.connection_fingerprint,
      context.rfc_message_id!,
      context.references[0]!,
      context.fingerprint,
      draft.recipient,
      draft.subject,
      JSON.stringify(draft.body_text),
      "resume.pdf",
      "1024",
      "version-1",
      "document-1",
      "profile-1",
      "b".repeat(64),
    ]) {
      expect(options.detail).toContain(expected);
    }
    expect(client.sendCommunicationDraft).toHaveBeenCalledExactlyOnceWith(
      draft.id,
      {
        fingerprint: draft.fingerprint,
        confirmed_by: "desktop-user",
        idempotency_key: expect.stringMatching(/^[\da-f-]{36}$/),
      },
    );
    await expect(
      invoke("communications:draft-send", draft.id, draft.fingerprint),
    ).rejects.toThrow(/already/);
    expect(client.sendCommunicationDraft).toHaveBeenCalledTimes(1);
  });
  it("cancels without a send and permits a later new native review", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 0 });
    await expect(
      invoke("communications:draft-send", draft.id, draft.fingerprint),
    ).resolves.toBeNull();
    expect(client.sendCommunicationDraft).not.toHaveBeenCalled();
    await invoke("communications:draft-send", draft.id, draft.fingerprint);
    expect(showMessageBox).toHaveBeenCalledTimes(2);
    expect(client.sendCommunicationDraft).toHaveBeenCalledTimes(1);
  });
  it("reviews standalone mode with a bound sending account and no thread", async () => {
    client.getCommunicationDraft.mockResolvedValue({
      ...draft,
      ...newMessage,
      provider_thread_id: "",
      reply_context: null,
    });
    await expect(
      invoke("communications:draft-send", draft.id, draft.fingerprint),
    ).resolves.toBe(accepted);
    const detail = showMessageBox.mock.calls[0]?.[0].detail;
    expect(detail).toContain("NEW_MESSAGE — standalone message, not a reply");
    expect(detail).toContain(context.account_label);
    expect(detail).not.toContain("Source thread:");
  });
  it("allows an empty original reply subject and quoted opaque source identifiers", async () => {
    client.getCommunicationDraft.mockResolvedValue({
      ...draft,
      subject: "",
      reply_context: {
        ...context,
        subject: "",
        source_message_id: "opaque/+=\u202eSource",
      },
    });
    await expect(
      invoke("communications:draft-send", draft.id, draft.fingerprint),
    ).resolves.toBe(accepted);
    const detail = showMessageBox.mock.calls[0]?.[0].detail;
    expect(detail).toContain('Subject: ""');
    expect(detail).toContain('Source message: "opaque/+=\\u202eSource"');
    expect(detail).not.toContain("\u202e");
  });
  it("allows text-only Outlook replies without MIME support, but not attachments", async () => {
    const outlook = {
      ...draft,
      provider: "OUTLOOK" as const,
      reply_context: {
        ...context,
        provider: "OUTLOOK" as const,
        source_id_format: "GRAPH_IMMUTABLE" as const,
        mime_reply_supported: false,
        rfc_message_id: null,
      },
    };
    client.getCommunicationDraft.mockResolvedValue(outlook);
    await expect(
      invoke("communications:draft-send", draft.id, draft.fingerprint),
    ).resolves.toEqual(notDispatched);
    expect(showMessageBox).not.toHaveBeenCalled();
    client.getCommunicationDraft.mockResolvedValue({
      ...outlook,
      document_version_ids: [],
      attachment_manifest: null,
    });
    await expect(
      invoke("communications:draft-send", draft.id, draft.fingerprint),
    ).resolves.toBe(accepted);
  });
  it.each([
    { mode: null },
    { mode: undefined },
    { account_key: null },
    { account_label: null },
    { reply_context: null },
    { reply_context: { ...context, account_key: "f".repeat(64) } },
    { reply_context: { ...context, recipient: "different@example.invalid" } },
    { reply_context: { ...context, source_record_id: "different-record" } },
    { reply_context: { ...context, rfc_message_id: null } },
    { reply_context: { ...context, mime_reply_supported: false } },
    {
      reply_context: { ...context, headers: { Bcc: "victim@example.invalid" } },
    },
    {
      reply_context: {
        ...context,
        references: Array(51).fill("<ref@example.invalid>"),
      },
    },
    {
      mode: "NEW_MESSAGE",
      reply_context: null,
      provider_thread_id: "old-thread",
    },
    { mode: "NEW_MESSAGE", provider_thread_id: "" },
  ])(
    "blocks legacy or inconsistent reply/account bindings before approval (%#)",
    async (change) => {
      client.getCommunicationDraft.mockResolvedValue({
        ...draft,
        ...change,
      } as OutboundDraft);
      await expect(
        invoke("communications:draft-send", draft.id, draft.fingerprint),
      ).resolves.toEqual(notDispatched);
      expect(showMessageBox).not.toHaveBeenCalled();
      expect(client.sendCommunicationDraft).not.toHaveBeenCalled();
    },
  );
  it.each([
    { policy_version: "mail-reply-v2" },
    { provider: "OUTLOOK", source_id_format: "GRAPH_IMMUTABLE" },
    { account_key: "f".repeat(64) },
    { account_label: "other-account@example.invalid" },
    { connection_fingerprint: "f".repeat(64) },
    { source_record_id: "analysis-other" },
    { source_message_id: "other/opaque+message=" },
    { source_thread_id: "another-thread" },
    { source_id_format: "GRAPH_IMMUTABLE" },
    { recipient: "other-recipient@example.invalid" },
    { subject: "Different subject" },
    { rfc_message_id: "<other@example.invalid>" },
    { references: ["<different@example.invalid>"] },
    { mime_reply_supported: false },
    { fingerprint: "f".repeat(64) },
  ])(
    "rejects changed reply context after approval even if the draft fingerprint is unchanged (%#)",
    async (change) => {
      const changedContext = { ...context, ...change } as MailReplyContext;
      client.getCommunicationDraft
        .mockResolvedValueOnce(draft)
        .mockResolvedValueOnce({
          ...draft,
          reply_context: changedContext,
          provider: changedContext.provider,
          account_key: changedContext.account_key,
          account_label: changedContext.account_label,
          analysis_id: changedContext.source_record_id,
          provider_thread_id: changedContext.source_thread_id,
          recipient: changedContext.recipient,
          subject: changedContext.subject,
        });
      await expect(
        invoke("communications:draft-send", draft.id, draft.fingerprint),
      ).resolves.toEqual(notDispatched);
      expect(showMessageBox).toHaveBeenCalledTimes(1);
      expect(client.sendCommunicationDraft).not.toHaveBeenCalled();
    },
  );
  it.each(
    [
      [],
      [draft.id],
      [draft.id, draft.fingerprint, { recipient: "attacker@example.invalid" }],
      ["../draft", draft.fingerprint],
      [draft.id, "0"],
      [draft.id, draft.fingerprint + "\n"],
    ].map((args) => ({ args })),
  )(
    "rejects invalid send arguments before reads/dialog (%#)",
    async ({ args }) => {
      await expect(
        invoke("communications:draft-send", ...args),
      ).rejects.toThrow(TypeError);
      expect(client.getCommunicationDraft).not.toHaveBeenCalled();
      expect(showMessageBox).not.toHaveBeenCalled();
    },
  );
  it.each(["ACCEPTED", "UNCERTAIN", "PLANNED", "CONFIRMED", "FAILED"] as const)(
    "returns a durable %s send audit and blocks another review",
    async (status) => {
      client.listCommunicationAudits.mockResolvedValue([
        { ...accepted, status },
      ]);
      await expect(
        invoke("communications:draft-send", draft.id, draft.fingerprint),
      ).resolves.toEqual({ ...accepted, status });
      await expect(
        invoke("communications:draft-send", draft.id, draft.fingerprint),
      ).rejects.toThrow(/already/);
      expect(showMessageBox).not.toHaveBeenCalled();
      expect(client.sendCommunicationDraft).not.toHaveBeenCalled();
    },
  );
  it("blocks stale review and changed draft contents after native approval", async () => {
    await expect(
      invoke("communications:draft-send", draft.id, "c".repeat(64)),
    ).resolves.toEqual(notDispatched);
    expect(showMessageBox).not.toHaveBeenCalled();
    client.getCommunicationDraft
      .mockResolvedValueOnce(draft)
      .mockResolvedValueOnce({
        ...draft,
        recipient: "changed@example.invalid",
      });
    await expect(
      invoke("communications:draft-send", draft.id, draft.fingerprint),
    ).resolves.toEqual(notDispatched);
    expect(client.sendCommunicationDraft).not.toHaveBeenCalled();
    await invoke("communications:draft-send", draft.id, draft.fingerprint);
    expect(showMessageBox).toHaveBeenCalledTimes(2);
    expect(client.sendCommunicationDraft).toHaveBeenCalledTimes(1);
  });
  it.each([
    { ...draft, attachment_manifest: null },
    {
      ...draft,
      attachment_manifest: { ...draft.attachment_manifest!, attachments: [] },
    },
    ...["version", "hash", "size", "mime", "name"].map((kind) => ({
      ...draft,
      attachment_manifest: {
        ...draft.attachment_manifest!,
        attachments: [
          {
            ...draft.attachment_manifest!.attachments[0]!,
            ...(kind === "version"
              ? { document_version_id: "other-version" }
              : kind === "hash"
                ? { sha256: "bad" }
                : kind === "size"
                  ? { size_bytes: 2 * 1024 * 1024 + 1 }
                  : kind === "mime"
                    ? { media_type: "application/javascript" }
                    : { file_name: "../resume.pdf" }),
          },
        ],
      },
    })),
  ])(
    "rejects missing or inconsistent backend manifest before approval (%#)",
    async (value) => {
      client.getCommunicationDraft.mockResolvedValue(value);
      await expect(
        invoke("communications:draft-send", draft.id, draft.fingerprint),
      ).resolves.toEqual(notDispatched);
      expect(showMessageBox).not.toHaveBeenCalled();
      expect(client.sendCommunicationDraft).not.toHaveBeenCalled();
    },
  );
  it("requires exact manifest version order, not merely membership equality", async () => {
    const first = draft.attachment_manifest!.attachments[0]!;
    client.getCommunicationDraft.mockResolvedValue({
      ...draft,
      document_version_ids: ["version-1", "version-2"],
      attachment_manifest: {
        ...draft.attachment_manifest!,
        attachments: [
          {
            ...first,
            document_version_id: "version-2",
            document_id: "document-2",
            file_name: "cover-letter.pdf",
          },
          first,
        ],
      },
    });
    await expect(
      invoke("communications:draft-send", draft.id, draft.fingerprint),
    ).resolves.toEqual(notDispatched);
    expect(showMessageBox).not.toHaveBeenCalled();
    expect(client.sendCommunicationDraft).not.toHaveBeenCalled();
  });
  it.each(["draft", "audits", "dialog", "final-draft"] as const)(
    "returns only sanitized pre-dispatch state after a %s failure and permits fresh approval",
    async (stage) => {
      const privateError = new Error(
        "private document, account and transport details",
      );
      if (stage === "draft")
        client.getCommunicationDraft.mockRejectedValueOnce(privateError);
      else if (stage === "audits")
        client.listCommunicationAudits.mockRejectedValueOnce(privateError);
      else if (stage === "dialog")
        showMessageBox.mockRejectedValueOnce(privateError);
      else
        client.getCommunicationDraft
          .mockResolvedValueOnce(draft)
          .mockRejectedValueOnce(privateError);

      await expect(
        invoke("communications:draft-send", draft.id, draft.fingerprint),
      ).resolves.toEqual(notDispatched);
      expect(client.sendCommunicationDraft).not.toHaveBeenCalled();
      expect(showMessageBox).toHaveBeenCalledTimes(
        stage === "dialog" || stage === "final-draft" ? 1 : 0,
      );

      await expect(
        invoke("communications:draft-send", draft.id, draft.fingerprint),
      ).resolves.toBe(accepted);
      expect(showMessageBox).toHaveBeenCalledTimes(
        stage === "dialog" || stage === "final-draft" ? 2 : 1,
      );
      expect(client.sendCommunicationDraft).toHaveBeenCalledTimes(1);
    },
  );
  it("blocks concurrent dialogs and never automatically retries a lost send response", async () => {
    let approve!: (value: { response: number }) => void;
    showMessageBox.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          approve = resolve;
        }),
    );
    const send = invoke(
      "communications:draft-send",
      draft.id,
      draft.fingerprint,
    );
    await vi.waitFor(() => expect(showMessageBox).toHaveBeenCalledTimes(1));
    await expect(
      invoke("communications:draft-send", draft.id, draft.fingerprint),
    ).rejects.toThrow(/already/);
    client.sendCommunicationDraft.mockRejectedValueOnce(
      new Error("private provider payload from lost HTTP response"),
    );
    approve({ response: 1 });
    await expect(send).rejects.toThrow(
      "Mail send outcome is unresolved; inspect the provider account.",
    );
    await expect(
      invoke("communications:draft-send", draft.id, draft.fingerprint),
    ).rejects.toThrow(/already/);
    expect(client.sendCommunicationDraft).toHaveBeenCalledTimes(1);
  });
});
