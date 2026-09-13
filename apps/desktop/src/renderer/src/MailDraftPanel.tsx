import { useCallback, useEffect, useRef, useState } from "react";

import type {
  CommunicationDraftCreate,
  CommunicationDraftMode,
  CommunicationMutationAudit,
  CommunicationRecord,
  OutboundDraft,
  WorkflowRunSnapshot,
} from "@job-apply-pro/contracts";

function outcome(audit: CommunicationMutationAudit): string {
  switch (audit.status) {
    case "ACCEPTED":
      return "Provider accepted this send; delivery is not confirmed. Do not resend this draft.";
    case "UNCERTAIN":
      return "Send outcome is uncertain. Inspect the provider account; do not retry or create a duplicate message.";
    case "CONFIRMED":
      return "Historical provider confirmation recorded; this is not proof of recipient delivery. Do not resend.";
    case "PLANNED":
      return "Send attempt reserved or in progress. Inspect the provider account before taking further action; do not retry.";
    case "FAILED":
      return "Send attempt failed. Review the audit and provider account before preparing a new draft; this draft cannot be resent.";
  }
}

function sourceSignature(record: CommunicationRecord | undefined): string {
  return JSON.stringify(
    record
      ? {
          id: record.id,
          provider: record.analysis.message.provider,
          message: record.analysis.message.provider_message_id,
          thread: record.analysis.message.provider_thread_id,
          context: record.reply_context,
          unavailable: record.reply_unavailable_reason,
        }
      : null,
  );
}

export function MailDraftPanel({
  backendReady,
  records,
  workflows,
}: {
  backendReady: boolean;
  records: CommunicationRecord[];
  workflows: WorkflowRunSnapshot[];
}) {
  const [drafts, setDrafts] = useState<OutboundDraft[]>([]);
  const [audits, setAudits] = useState<CommunicationMutationAudit[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [recordId, setRecordId] = useState("");
  const [mode, setMode] = useState<CommunicationDraftMode>("REPLY");
  const [preparedSource, setPreparedSource] = useState<string | null>(null);
  const [workflowId, setWorkflowId] = useState("");
  const [recipient, setRecipient] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [versionInput, setVersionInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<Set<string>>(new Set());
  const generation = useRef(0);
  const active = useRef(false);

  const refresh = useCallback(async () => {
    if (!backendReady || active.current) return;
    const request = ++generation.current;
    active.current = true;
    setBusy(true);
    setLoaded(false);
    setError(null);
    try {
      const api = window.jobApplyPro.workbench;
      const [nextDrafts, nextAudits] = await Promise.all([
        api.listCommunicationDrafts(),
        api.listCommunicationAudits(),
      ]);
      if (request !== generation.current) return;
      setDrafts(nextDrafts);
      setAudits(nextAudits);
      setLoaded(true);
    } catch {
      if (request === generation.current)
        setError(
          "Mail drafts and send audit could not be loaded. Refresh before reviewing a send.",
        );
    } finally {
      if (request === generation.current) {
        active.current = false;
        setBusy(false);
      }
    }
  }, [backendReady]);

  useEffect(() => {
    setDrafts([]);
    setAudits([]);
    setSelectedId("");
    setLoaded(false);
    active.current = false;
    setBusy(false);
    if (backendReady) void refresh();
    return () => {
      generation.current += 1;
    };
  }, [backendReady, refresh]);

  const mailRecords = records.filter(
    (record) =>
      record.analysis.message.provider === "GMAIL" ||
      record.analysis.message.provider === "OUTLOOK",
  );
  const source = mailRecords.find((record) => record.id === recordId);
  const sourceKey = sourceSignature(source);
  const currentSource = useRef(sourceKey);
  currentSource.current = sourceKey;
  const sourceChanged = preparedSource !== null && preparedSource !== sourceKey;
  const reply = source?.reply_context;
  const replyAvailable =
    !!reply &&
    !source?.reply_unavailable_reason &&
    reply.source_record_id === source?.id &&
    reply.provider === source?.analysis.message.provider &&
    reply.source_message_id === source?.analysis.message.provider_message_id &&
    reply.source_thread_id === source?.analysis.message.provider_thread_id &&
    (reply.provider !== "GMAIL" ||
      (!!reply.rfc_message_id && reply.mime_reply_supported));
  const draft = drafts.find((item) => item.id === selectedId);
  const prior = draft
    ? audits.find(
        (audit) =>
          audit.kind === "SEND_MESSAGE" && audit.resource_id === draft.id,
      )
    : undefined;
  const versions = versionInput.split(/[\s,]+/).filter(Boolean);
  const versionsValid =
    versions.length <= 4 &&
    new Set(versions).size === versions.length &&
    versions.every((id) => /^[a-zA-Z0-9_-]{1,100}$/.test(id)) &&
    (!versions.length || !!workflowId);
  const canCreate =
    backendReady &&
    loaded &&
    !busy &&
    !!source &&
    !sourceChanged &&
    versionsValid &&
    (mode === "REPLY"
      ? replyAvailable && (!versions.length || reply?.mime_reply_supported)
      : !!recipient.trim() && !!subject.trim()) &&
    !!body.trim();
  const manifestMissing =
    !!draft?.document_version_ids.length && !draft.attachment_manifest;
  const bindingMissing =
    !!draft &&
    (!draft.account_key ||
      !draft.account_label ||
      (draft.mode !== "REPLY" && draft.mode !== "NEW_MESSAGE") ||
      (draft.mode === "REPLY" && !draft.reply_context) ||
      (draft.mode === "NEW_MESSAGE" &&
        (draft.reply_context !== null || draft.provider_thread_id !== "")));
  const offlinePreview =
    draft?.mode === "NEW_MESSAGE" &&
    draft.account_key === null &&
    draft.account_label === null &&
    draft.reply_context === null &&
    draft.provider_thread_id === "";
  const canSend =
    backendReady &&
    loaded &&
    !busy &&
    !!draft &&
    draft.policy === "REVIEW_REQUIRED" &&
    !prior &&
    !blocked.has(draft.id) &&
    !bindingMissing &&
    !manifestMissing;

  function chooseRecord(id: string) {
    setRecordId(id);
    const record = mailRecords.find((item) => item.id === id);
    setPreparedSource(sourceSignature(record));
    setSelectedId("");
    setWorkflowId(record?.analysis.correlation.workflow_id ?? "");
    setRecipient(record?.reply_context?.recipient ?? "");
    setSubject(
      record?.reply_context?.subject ??
        record?.analysis.reply_draft.subject ??
        "",
    );
    setBody(record?.analysis.reply_draft.body_text ?? "");
    setVersionInput("");
    setNotice(null);
    setError(null);
  }

  function chooseMode(nextMode: CommunicationDraftMode) {
    setMode(nextMode);
    setSelectedId("");
    setRecipient(reply?.recipient ?? "");
    setSubject(reply?.subject ?? source?.analysis.reply_draft.subject ?? "");
    setNotice(null);
    setError(null);
  }

  async function createDraft() {
    if (!canCreate || !source || active.current) return;
    active.current = true;
    const request = ++generation.current;
    setBusy(true);
    setError(null);
    setNotice(null);
    const common = {
      analysis_id: source.id,
      workflow_id: workflowId || null,
      body_text: body,
      category: source.analysis.reply_draft.category,
      policy: "REVIEW_REQUIRED" as const,
      document_version_ids: versions,
    };
    const input: CommunicationDraftCreate =
      mode === "REPLY"
        ? {
            ...common,
            mode: "REPLY",
            source_fingerprint: reply!.fingerprint,
          }
        : {
            ...common,
            mode: "NEW_MESSAGE",
            provider: source.analysis.message.provider as "GMAIL" | "OUTLOOK",
            recipient,
            subject,
          };
    try {
      const created =
        await window.jobApplyPro.workbench.createCommunicationDraft(input);
      if (request !== generation.current) return;
      if (currentSource.current !== sourceKey) {
        setSelectedId("");
        setNotice(
          "Source or sending-account context changed during preparation. Refresh mail drafts and reload the source before preparing a fresh draft. No send was requested.",
        );
        return;
      }
      setDrafts((items) => [
        created,
        ...items.filter((item) => item.id !== created.id),
      ]);
      setSelectedId(created.id);
      setNotice(
        created.mode === "NEW_MESSAGE" &&
          created.account_key === null &&
          created.account_label === null
          ? "Offline standalone preview saved locally. It is not send-ready. Connect the provider and prepare a fresh draft for native review; this preview will not be bound to a new account. Nothing has been sent."
          : "Draft saved for review only. Nothing has been sent. Review the verified manifest before native approval.",
      );
    } catch {
      if (request === generation.current)
        setError(
          "Draft was not created. Check the recipient, owning workflow and immutable PDF/DOCX versions (four maximum, 2 MiB combined). No message was sent.",
        );
    } finally {
      if (request === generation.current) {
        active.current = false;
        setBusy(false);
      }
    }
  }

  async function sendDraft() {
    if (!canSend || !draft || active.current) return;
    active.current = true;
    const request = ++generation.current;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await window.jobApplyPro.workbench.sendCommunicationDraft(
        draft.id,
        draft.fingerprint,
      );
      if (request !== generation.current) return;
      if (result === null) {
        setNotice("Native approval cancelled. No message was sent.");
      } else if ("outcome" in result) {
        if (
          result.outcome !== "NOT_DISPATCHED" ||
          result.reason !== "REVIEW_UNAVAILABLE"
        ) {
          throw new Error("Mail review result is invalid.");
        }
        setLoaded(false);
        setNotice(
          "No send was dispatched by this review. Refresh mail drafts and review again.",
        );
      } else {
        setBlocked((ids) => new Set([...ids, draft.id]));
        setAudits((items) => [
          result,
          ...items.filter((item) => item.id !== result.id),
        ]);
        setNotice(outcome(result));
      }
    } catch {
      if (request !== generation.current) return;
      // A lost IPC/HTTP response is not evidence that no send happened. No auto retry.
      setBlocked((ids) => new Set([...ids, draft.id]));
      setError(
        "Send result could not be confirmed. Inspect the provider account and refresh the audit; do not retry or create a duplicate message.",
      );
    } finally {
      if (request === generation.current) {
        active.current = false;
        setBusy(false);
      }
    }
  }

  return (
    <section
      className="mail-draft-panel"
      aria-labelledby="mail-draft-title"
      aria-busy={busy}
    >
      <div className="panel__header panel__header--subsection">
        <div>
          <h3 id="mail-draft-title">Reviewed email & verified attachments</h3>
          <p>
            Messages are never sent automatically. Choose a source-bound reply
            or an explicit standalone new message. Attachment contents stay in
            the encrypted backend; only verified metadata is shown here.
          </p>
        </div>
        <button
          className="button button--secondary"
          type="button"
          disabled={!backendReady || busy}
          onClick={() => void refresh()}
        >
          Refresh mail drafts
        </button>
      </div>
      {!backendReady && (
        <p role="status">Connect the local backend to review mail drafts.</p>
      )}
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="warning-banner">
          {notice}
        </p>
      )}
      <form
        className="workbench-form"
        onSubmit={(event) => {
          event.preventDefault();
          void createDraft();
        }}
      >
        <label>
          Imported source message
          <select
            value={recordId}
            disabled={!backendReady || busy}
            onChange={(event) => chooseRecord(event.target.value)}
          >
            <option value="">Choose a message</option>
            {mailRecords.map((record) => (
              <option key={record.id} value={record.id}>
                {record.analysis.message.provider} ·{" "}
                {record.analysis.message.subject}
              </option>
            ))}
          </select>
        </label>
        <label>
          Message mode
          <select
            value={mode}
            disabled={!backendReady || busy}
            onChange={(event) =>
              chooseMode(event.target.value as CommunicationDraftMode)
            }
          >
            <option value="REPLY">Reply in the source conversation</option>
            <option value="NEW_MESSAGE">
              New standalone message (not a reply)
            </option>
          </select>
        </label>
        {source && (
          <div className="mail-draft-panel__wide">
            <p>
              Source: {source.analysis.message.provider} ·{" "}
              {source.analysis.message.subject}
            </p>
            <p>Received: {source.analysis.message.received_at}</p>
            {reply && (
              <>
                <p>Source account: {reply.account_label}</p>
                <p>
                  Source message: <code>{reply.source_message_id}</code> ·
                  Thread: <code>{reply.source_thread_id}</code>
                </p>
                <p>
                  Source fingerprint: <code>{reply.fingerprint}</code>
                </p>
              </>
            )}
            {mode === "REPLY" && (
              <p>
                Reply recipient and subject are fixed by the verified source.
                Reply-all and recipient overrides are not supported.
              </p>
            )}
            {mode === "REPLY" && !replyAvailable && (
              <p role="status">
                Threaded reply is unavailable for this source. Sync an eligible
                source message, or explicitly choose a new standalone message.
                No automatic fallback.
              </p>
            )}
            {mode === "NEW_MESSAGE" && (
              <p>
                This is a new standalone message, not a reply. Review its
                sending account, recipient and subject in native approval.
              </p>
            )}
            {sourceChanged && (
              <p role="status">
                Source or sending-account context changed. Reload the source and
                review it again before saving.
              </p>
            )}
            {sourceChanged && (
              <button
                type="button"
                disabled={busy}
                onClick={() => chooseRecord(recordId)}
              >
                Reload source context
              </button>
            )}
          </div>
        )}
        <label>
          Owning workflow (required for attachments)
          <select
            value={workflowId}
            disabled={!source || busy}
            onChange={(event) => setWorkflowId(event.target.value)}
          >
            <option value="">No workflow</option>
            {workflowId &&
              !workflows.some((item) => item.workflow_id === workflowId) && (
                <option value={workflowId}>
                  {workflowId} — verify ownership
                </option>
              )}
            {workflows.map((workflow) => (
              <option key={workflow.workflow_id} value={workflow.workflow_id}>
                {workflow.employer} · {workflow.title} · {workflow.workflow_id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Recipient email
          <input
            type="email"
            required={mode === "NEW_MESSAGE"}
            value={mode === "REPLY" ? (reply?.recipient ?? "") : recipient}
            maxLength={mode === "REPLY" ? 320 : 254}
            disabled={!source || busy}
            readOnly={mode === "REPLY"}
            onChange={(event) => setRecipient(event.target.value)}
          />
        </label>
        <label>
          Message subject
          <input
            required={mode === "NEW_MESSAGE"}
            value={mode === "REPLY" ? (reply?.subject ?? "") : subject}
            maxLength={1000}
            disabled={!source || busy}
            readOnly={mode === "REPLY"}
            onChange={(event) => setSubject(event.target.value)}
          />
        </label>
        <label className="mail-draft-panel__wide">
          Message body
          <textarea
            required
            value={body}
            maxLength={20000}
            rows={6}
            disabled={!source || busy}
            onChange={(event) => setBody(event.target.value)}
          />
        </label>
        <label className="mail-draft-panel__wide">
          Immutable document version IDs (optional)
          <textarea
            value={versionInput}
            maxLength={404}
            rows={2}
            spellCheck={false}
            autoComplete="off"
            disabled={!source || busy}
            onChange={(event) => setVersionInput(event.target.value)}
            aria-describedby="mail-attachment-policy"
          />
        </label>
        <p id="mail-attachment-policy" className="mail-draft-panel__wide">
          Separate exact version IDs with spaces or commas. Up to four unique
          PDF/DOCX versions, 2 MiB combined. Resumes, cover letters,
          certifications, education records and portfolios are supported; other
          document kinds are not. For recruiter outreach without a linked
          workflow, select an application workflow before attaching documents.
          The backend verifies workflow ownership, content hashes and file types
          before saving the approval-bound manifest.
        </p>
        {!versionsValid && (
          <p role="alert" className="mail-draft-panel__wide">
            Attachments need an owning workflow and at most four unique version
            IDs.
          </p>
        )}
        <button
          className="button button--secondary"
          type="submit"
          disabled={!canCreate}
        >
          {mode === "REPLY"
            ? "Save reply for review"
            : "Save new message for review"}
        </button>
      </form>
      <label className="mail-draft-panel__selection">
        Saved mail draft
        <select
          value={selectedId}
          disabled={!loaded || busy}
          onChange={(event) => {
            setSelectedId(event.target.value);
            setNotice(null);
            setError(null);
          }}
        >
          <option value="">Choose a saved draft</option>
          {drafts.map((item) => (
            <option key={item.id} value={item.id}>
              {item.provider} · {item.subject} · {item.id}
            </option>
          ))}
        </select>
      </label>
      {draft && (
        <article className="mail-draft-review">
          <h4>Exact saved message</h4>
          <p>
            Mode:{" "}
            {draft.mode === "REPLY"
              ? "Reply in the source conversation"
              : draft.mode === "NEW_MESSAGE"
                ? "New standalone message (not a reply)"
                : "Legacy draft — mode unavailable"}
          </p>
          <p>
            Sending account: {draft.account_label ?? "Unavailable"} · Account
            binding: <code>{draft.account_key ?? "Unavailable"}</code>
          </p>
          <p>
            Provider: {draft.provider} · Recipient: {draft.recipient}
          </p>
          <p>Subject: {draft.subject}</p>
          <pre>{draft.body_text}</pre>
          {draft.reply_context && (
            <>
              <h4>Immutable reply context</h4>
              <p>
                Source record:{" "}
                <code>{draft.reply_context.source_record_id}</code> · Message:{" "}
                <code>{draft.reply_context.source_message_id}</code> · Thread:{" "}
                <code>{draft.reply_context.source_thread_id}</code>
              </p>
              <p>
                Source ID format: {draft.reply_context.source_id_format} ·
                Policy: {draft.reply_context.policy_version}
              </p>
              <p>
                Connection fingerprint:{" "}
                <code>{draft.reply_context.connection_fingerprint}</code>
              </p>
              <p>
                RFC Message-ID:{" "}
                <code>{draft.reply_context.rfc_message_id ?? "None"}</code>
              </p>
              <p>
                References:{" "}
                <code>{JSON.stringify(draft.reply_context.references)}</code>
              </p>
              <p>
                MIME reply supported:{" "}
                {draft.reply_context.mime_reply_supported ? "Yes" : "No"}
              </p>
              <p>
                Source fingerprint:{" "}
                <code>{draft.reply_context.fingerprint}</code>
              </p>
            </>
          )}
          {offlinePreview ? (
            <p className="warning-banner">
              Offline preview — not send-ready. No sending account is bound.
              After connecting the provider, prepare a fresh draft for native
              review. Connecting or refreshing cannot make this preview
              sendable.
            </p>
          ) : (
            bindingMissing && (
              <p className="warning-banner">
                This draft has no valid explicit mode or immutable account/reply
                binding. Prepare a fresh reviewed draft; this draft cannot be
                sent.
              </p>
            )
          )}
          <p>
            Workflow: {draft.workflow_id ?? "None"} · Attachment profile:{" "}
            {draft.attachment_manifest?.profile_id ?? "None"}
          </p>
          <h4>
            Verified attachment manifest (
            {draft.attachment_manifest?.attachments.length ?? 0})
          </h4>
          {manifestMissing ? (
            <p className="warning-banner">
              Legacy draft has no verified attachment manifest. Prepare a fresh
              reviewed draft; this draft cannot be sent.
            </p>
          ) : !draft.attachment_manifest ? (
            <p>No attachments.</p>
          ) : (
            <ul>
              {draft.attachment_manifest.attachments.map((item) => (
                <li key={item.document_version_id}>
                  <strong>{item.file_name}</strong> ·{" "}
                  {item.size_bytes.toLocaleString()} bytes · {item.media_type}
                  <div>
                    Version: <code>{item.document_version_id}</code> · Document:{" "}
                    <code>{item.document_id}</code>
                  </div>
                  <div>
                    SHA-256: <code>{item.sha256}</code>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <p>
            Review fingerprint: <code>{draft.fingerprint}</code>
          </p>
          {prior && <p className="warning-banner">{outcome(prior)}</p>}
          {!prior && blocked.has(draft.id) && (
            <p className="warning-banner">
              A send result is unresolved in this session. Inspect the provider
              account; do not resend.
            </p>
          )}
          <button
            className="button button--primary"
            type="button"
            disabled={!canSend}
            onClick={() => void sendDraft()}
          >
            Review & send with native approval
          </button>
          <p>
            Native approval reloads the saved draft. Provider acceptance is not
            delivery confirmation. No automatic send retries.
          </p>
        </article>
      )}
    </section>
  );
}
