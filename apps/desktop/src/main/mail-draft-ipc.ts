import { randomUUID } from "node:crypto";

import { BrowserWindow, dialog, ipcMain } from "electron";

import type {
  CommunicationDraftCreate,
  CommunicationDraftSendResult,
  MailReplyContext,
  MessageCategory,
  OutboundDraft,
} from "@job-apply-pro/contracts";

import type { BackendClient } from "./backend-client.js";

const categories = new Set<MessageCategory>([
  "RECRUITER_INQUIRY",
  "INTERVIEW_REQUEST",
  "SCREENING_REQUEST",
  "ASSESSMENT_INVITATION",
  "APPLICATION_CONFIRMATION",
  "STATUS_UPDATE",
  "REJECTION",
  "OFFER",
  "JOB_ALERT",
  "NEWSLETTER",
  "SPAM_OR_UNRELATED",
]);
const createKeys = new Set([
  "mode",
  "analysis_id",
  "workflow_id",
  "body_text",
  "category",
  "policy",
  "document_version_ids",
]);

function identifier(value: unknown): string {
  if (typeof value !== "string" || !/^[a-zA-Z0-9_-]{1,100}$/.test(value)) {
    throw new TypeError("Mail record identifier is invalid.");
  }
  return value;
}

function fingerprint(value: unknown): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) {
    throw new TypeError("Mail review fingerprint is invalid.");
  }
  return value;
}

function text(
  value: unknown,
  limit: number,
  multiline = false,
  allowEmpty = false,
): string {
  if (
    typeof value !== "string" ||
    (!allowEmpty && !value.trim()) ||
    value.length > limit ||
    [...value].some((character) => {
      const code = character.charCodeAt(0);
      return (
        code === 127 ||
        (code < 32 && !(multiline && [9, 10, 13].includes(code)))
      );
    })
  ) {
    throw new TypeError("Mail review text is invalid.");
  }
  return value;
}

export function validateCommunicationDraftCreate(
  value: unknown,
): CommunicationDraftCreate {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  ) {
    throw new TypeError("Mail draft input is invalid.");
  }
  const input = value as Record<string, unknown>;
  const keys = new Set([
    ...createKeys,
    ...(input.mode === "REPLY"
      ? ["source_fingerprint"]
      : ["provider", "recipient", "subject"]),
  ]);
  if (
    (input.mode !== "REPLY" && input.mode !== "NEW_MESSAGE") ||
    Reflect.ownKeys(input).length !== keys.size ||
    Reflect.ownKeys(input).some(
      (key) => typeof key !== "string" || !keys.has(key),
    ) ||
    input.policy !== "REVIEW_REQUIRED" ||
    !categories.has(input.category as MessageCategory)
  ) {
    throw new TypeError(
      "Mail provider, category, or review policy is invalid.",
    );
  }
  const versions = input.document_version_ids;
  if (
    !Array.isArray(versions) ||
    versions.length > 4 ||
    new Set(versions).size !== versions.length
  ) {
    throw new TypeError("Choose at most four unique document versions.");
  }
  const versionIds = versions.map(identifier);
  const workflowId =
    input.workflow_id === null ? null : identifier(input.workflow_id);
  if (versionIds.length && !workflowId) {
    throw new TypeError("Attachments require an owning workflow.");
  }
  const common = {
    analysis_id: identifier(input.analysis_id),
    workflow_id: workflowId,
    body_text: text(input.body_text, 20_000, true),
    category: input.category as MessageCategory,
    policy: "REVIEW_REQUIRED" as const,
    document_version_ids: versionIds,
  };
  if (input.mode === "REPLY") {
    return {
      ...common,
      mode: "REPLY",
      source_fingerprint: fingerprint(input.source_fingerprint),
    };
  }
  if (input.provider !== "GMAIL" && input.provider !== "OUTLOOK") {
    throw new TypeError("Mail provider is invalid.");
  }
  return {
    ...common,
    mode: "NEW_MESSAGE",
    provider: input.provider,
    recipient: email(input.recipient),
    subject: text(input.subject, 1_000),
  };
}

function email(value: unknown, limit = 254): string {
  const recipient = text(value, Math.min(limit, 254));
  const match =
    /^([A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*)@([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)$/.exec(
      recipient,
    );
  if (
    !match ||
    match[1]!.length > 64 ||
    match[2]!
      .split(".")
      .some(
        (label) =>
          label.length < 1 ||
          label.length > 63 ||
          label.startsWith("-") ||
          label.endsWith("-"),
      )
  ) {
    throw new TypeError("Review one email recipient address.");
  }
  return recipient;
}

function replyContext(value: unknown): MailReplyContext {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("A source-bound reply context is required.");
  }
  const context = value as Record<string, unknown>;
  const keys = [
    "policy_version",
    "provider",
    "account_key",
    "account_label",
    "connection_fingerprint",
    "source_record_id",
    "source_message_id",
    "source_thread_id",
    "source_id_format",
    "recipient",
    "subject",
    "rfc_message_id",
    "references",
    "mime_reply_supported",
    "fingerprint",
  ];
  if (
    Reflect.ownKeys(context).length !== keys.length ||
    Reflect.ownKeys(context).some(
      (key) => typeof key !== "string" || !keys.includes(key),
    ) ||
    context.policy_version !== "mail-reply-v1" ||
    (context.provider !== "GMAIL" && context.provider !== "OUTLOOK") ||
    context.source_id_format !==
      (context.provider === "GMAIL" ? "GMAIL" : "GRAPH_IMMUTABLE") ||
    typeof context.mime_reply_supported !== "boolean" ||
    !Array.isArray(context.references) ||
    context.references.length > 50
  ) {
    throw new TypeError("Reply review context is invalid.");
  }
  return {
    policy_version: "mail-reply-v1",
    provider: context.provider,
    account_key: fingerprint(context.account_key),
    account_label: email(context.account_label, 320),
    connection_fingerprint: fingerprint(context.connection_fingerprint),
    source_record_id: text(context.source_record_id, 100),
    source_message_id: text(context.source_message_id, 500),
    source_thread_id: text(context.source_thread_id, 500),
    source_id_format:
      context.source_id_format as MailReplyContext["source_id_format"],
    recipient: email(context.recipient, 320),
    subject: text(context.subject, 1_000, false, true),
    rfc_message_id:
      context.rfc_message_id === null
        ? null
        : text(context.rfc_message_id, 998),
    references: context.references.map((item) => text(item, 998)),
    mime_reply_supported: context.mime_reply_supported,
    fingerprint: fingerprint(context.fingerprint),
  };
}

// Quote strings and visibly escape directional controls; remote text must never
// be able to masquerade as the surrounding native approval instructions.
function quoted(value: string): string {
  return JSON.stringify(value).replace(
    /[\u2028-\u202e\u2066-\u2069]/g,
    (character) =>
      `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
}

function reviewDetails(draft: OutboundDraft): string {
  if (
    draft.policy !== "REVIEW_REQUIRED" ||
    (draft.mode !== "REPLY" && draft.mode !== "NEW_MESSAGE")
  ) {
    throw new TypeError("A fresh review-required mail draft is required.");
  }
  const context =
    draft.mode === "REPLY" ? replyContext(draft.reply_context) : null;
  const accountKey = fingerprint(draft.account_key);
  const accountLabel = email(draft.account_label, 320);
  const recipient = email(draft.recipient, draft.mode === "REPLY" ? 320 : 254);
  const subject = text(draft.subject, 1_000, false, draft.mode === "REPLY");
  if (
    context
      ? context.provider !== draft.provider ||
        context.source_record_id !== draft.analysis_id ||
        context.source_thread_id !== draft.provider_thread_id ||
        context.recipient !== recipient ||
        context.subject !== subject ||
        context.account_key !== accountKey ||
        context.account_label !== accountLabel ||
        (draft.provider === "GMAIL" &&
          (!context.mime_reply_supported || context.rfc_message_id === null)) ||
        (draft.document_version_ids.length > 0 && !context.mime_reply_supported)
      : draft.reply_context !== null || draft.provider_thread_id !== ""
  ) {
    throw new TypeError(
      "Draft reply context does not match the reviewed message.",
    );
  }
  const input = validateCommunicationDraftCreate({
    analysis_id: draft.analysis_id,
    workflow_id: draft.workflow_id,
    ...(context
      ? {
          mode: "REPLY",
          source_fingerprint: context.fingerprint,
        }
      : {
          mode: "NEW_MESSAGE",
          provider: draft.provider,
          recipient,
          subject,
        }),
    body_text: draft.body_text,
    category: draft.category,
    policy: draft.policy,
    document_version_ids: draft.document_version_ids,
  });
  fingerprint(draft.fingerprint);
  const manifest = draft.attachment_manifest;
  const attachments: string[] = [];
  if (input.document_version_ids.length) {
    if (
      !manifest ||
      manifest.policy_version !== "mail-attachments-v1" ||
      !Array.isArray(manifest.attachments) ||
      manifest.attachments.length !== input.document_version_ids.length
    ) {
      throw new TypeError("A verified attachment manifest is required.");
    }
    identifier(manifest.profile_id);
    let totalBytes = 0;
    const seen = new Set<string>();
    for (const [index, item] of manifest.attachments.entries()) {
      const version = identifier(item.document_version_id);
      if (input.document_version_ids[index] !== version || seen.has(version)) {
        throw new TypeError("Attachment version manifest does not match.");
      }
      seen.add(version);
      identifier(item.document_id);
      fingerprint(item.sha256);
      const name = text(item.file_name, 200);
      if (
        /[\\/:]/.test(name) ||
        name !== name.trim() ||
        !(
          (item.media_type === "application/pdf" && /\.pdf$/i.test(name)) ||
          (item.media_type ===
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document" &&
            /\.docx$/i.test(name))
        ) ||
        !Number.isSafeInteger(item.size_bytes) ||
        item.size_bytes <= 0
      ) {
        throw new TypeError("Attachment review metadata is invalid.");
      }
      totalBytes += item.size_bytes;
      attachments.push(
        [
          `File: ${quoted(name)}`,
          `Type: ${item.media_type}`,
          `Bytes: ${item.size_bytes}`,
          `Version: ${version}`,
          `Document: ${item.document_id}`,
          `SHA-256: ${item.sha256}`,
        ].join("\n"),
      );
    }
    if (totalBytes > 2 * 1024 * 1024)
      throw new TypeError("Attachment review size exceeds policy.");
  } else if (manifest !== null) {
    throw new TypeError("Unexpected attachment manifest.");
  }
  return [
    `Mode: ${draft.mode === "REPLY" ? "REPLY — source-bound reply" : "NEW_MESSAGE — standalone message, not a reply"}`,
    `Provider: ${draft.provider}`,
    `Sending account: ${quoted(accountLabel)}`,
    `Account binding SHA-256: ${accountKey}`,
    `Source record: ${quoted(draft.analysis_id)}`,
    ...(context
      ? [
          `Reply policy: ${context.policy_version}`,
          `Source message: ${quoted(context.source_message_id)}`,
          `Source thread: ${quoted(context.source_thread_id)}`,
          `Source ID format: ${context.source_id_format}`,
          `Connection SHA-256: ${context.connection_fingerprint}`,
          `RFC Message-ID: ${context.rfc_message_id === null ? "None" : quoted(context.rfc_message_id)}`,
          `References: ${quoted(JSON.stringify(context.references))}`,
          `MIME reply supported: ${context.mime_reply_supported ? "Yes" : "No"}`,
          `Source review SHA-256: ${context.fingerprint}`,
        ]
      : []),
    `Recipient: ${quoted(recipient)}`,
    `Subject: ${quoted(subject)}`,
    `Body (quoted exactly):\n${quoted(input.body_text)}`,
    `Workflow: ${input.workflow_id ?? "None"}`,
    `Profile: ${manifest?.profile_id ?? "No attachments"}`,
    `Attachments: ${attachments.length}`,
    ...attachments,
    `Review SHA-256: ${draft.fingerprint}`,
    "This sends the reviewed message and exact attached versions. Provider acceptance does not prove delivery. Do not retry an uncertain send; inspect the provider account.",
  ].join("\n\n");
}

export function registerMailDraftIpc(client: BackendClient): void {
  // A dispatched send remains blocked in this process even if the HTTP response
  // is lost. Durable per-draft backend claims enforce the same rule on restart.
  const attempts = new Map<string, "reviewing" | "dispatched">();
  ipcMain.handle("communications:drafts-list", (_event, ...args: unknown[]) => {
    if (args.length) throw new TypeError("Draft listing accepts no arguments.");
    return client.listCommunicationDrafts();
  });
  ipcMain.handle("communications:audits-list", (_event, ...args: unknown[]) => {
    if (args.length)
      throw new TypeError("Mail audit listing accepts no arguments.");
    return client.listCommunicationAudits();
  });
  ipcMain.handle(
    "communications:draft-create",
    async (_event, ...args: unknown[]) => {
      if (args.length !== 1)
        throw new TypeError("One mail draft input is required.");
      const input = validateCommunicationDraftCreate(args[0]);
      try {
        return await client.createCommunicationDraft(input);
      } catch {
        throw new Error(
          "Mail draft could not be prepared. Refresh the source and review again. No send was requested.",
        );
      }
    },
  );
  ipcMain.handle(
    "communications:draft-send",
    async (
      event,
      ...args: unknown[]
    ): Promise<CommunicationDraftSendResult> => {
      if (args.length !== 2)
        throw new TypeError("Draft id and reviewed fingerprint are required.");
      const id = identifier(args[0]);
      const reviewed = fingerprint(args[1]);
      if (attempts.has(id))
        throw new Error(
          "This draft already has a review or send attempt; inspect its outcome.",
        );
      attempts.set(id, "reviewing");
      try {
        const draft = await client.getCommunicationDraft(id);
        if (draft.id !== id || draft.fingerprint !== reviewed)
          throw new Error("Draft changed; refresh and review.");
        const detail = reviewDetails(draft);
        const audits = await client.listCommunicationAudits();
        const prior = audits.find(
          (audit) => audit.kind === "SEND_MESSAGE" && audit.resource_id === id,
        );
        if (prior) {
          attempts.set(id, "dispatched");
          return prior;
        }
        const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
        const options = {
          type: "warning" as const,
          title: "Review outbound email",
          message: "Send this exact message and these exact attachments?",
          detail,
          buttons: ["Cancel", "Send reviewed email"],
          defaultId: 0,
          cancelId: 0,
          noLink: true,
        };
        const result = owner
          ? await dialog.showMessageBox(owner, options)
          : await dialog.showMessageBox(options);
        if (result.response !== 1) return null;
        const current = await client.getCommunicationDraft(id);
        if (
          current.id !== id ||
          current.fingerprint !== reviewed ||
          reviewDetails(current) !== detail
        ) {
          throw new Error("Draft changed during approval; refresh and review.");
        }
        attempts.set(id, "dispatched");
        return await client.sendCommunicationDraft(id, {
          fingerprint: reviewed,
          idempotency_key: randomUUID(),
          confirmed_by: "desktop-user",
        });
      } catch {
        if (attempts.get(id) === "reviewing") {
          // Reads, validation and the native dialog have no provider side effect.
          // Do not expose backend, dialog or document details through IPC errors.
          return { outcome: "NOT_DISPATCHED", reason: "REVIEW_UNAVAILABLE" };
        }
        // Dispatch may have succeeded even when its response was lost. Never
        // return a retryable preflight result or the private underlying error.
        throw new Error(
          "Mail send outcome is unresolved; inspect the provider account.",
        );
      } finally {
        if (attempts.get(id) === "reviewing") attempts.delete(id);
      }
    },
  );
}
