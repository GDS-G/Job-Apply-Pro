import { useCallback, useEffect, useRef, useState } from "react";

import type {
  CommunicationDraftCreate,
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

function address(sender: string): string {
  const match = /<([^<>]+)>$/.exec(sender);
  return (match?.[1] ?? sender).trim();
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
    versionsValid &&
    !!recipient.trim() &&
    !!subject.trim() &&
    !!body.trim();
  const manifestMissing =
    !!draft?.document_version_ids.length && !draft.attachment_manifest;
  const canSend =
    backendReady &&
    loaded &&
    !busy &&
    !!draft &&
    draft.policy === "REVIEW_REQUIRED" &&
    !prior &&
    !blocked.has(draft.id) &&
    !manifestMissing;

  function chooseRecord(id: string) {
    setRecordId(id);
    const record = mailRecords.find((item) => item.id === id);
    setWorkflowId(record?.analysis.correlation.workflow_id ?? "");
    setRecipient(record ? address(record.analysis.message.sender) : "");
    setSubject(record?.analysis.reply_draft.subject ?? "");
    setBody(record?.analysis.reply_draft.body_text ?? "");
    setVersionInput("");
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
    const input: CommunicationDraftCreate = {
      analysis_id: source.id,
      workflow_id: workflowId || null,
      provider: source.analysis.message.provider as "GMAIL" | "OUTLOOK",
      provider_thread_id: source.analysis.message.provider_thread_id,
      recipient,
      subject,
      body_text: body,
      category: source.analysis.reply_draft.category,
      policy: "REVIEW_REQUIRED",
      document_version_ids: versions,
    };
    try {
      const created =
        await window.jobApplyPro.workbench.createCommunicationDraft(input);
      if (request !== generation.current) return;
      setDrafts((items) => [
        created,
        ...items.filter((item) => item.id !== created.id),
      ]);
      setSelectedId(created.id);
      setNotice(
        "Draft saved for review only. Nothing has been sent. Review the verified manifest before native approval.",
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
            Replies are never sent automatically. Attachment contents stay in
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
          Reply to imported message
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
            required
            value={recipient}
            maxLength={254}
            disabled={!source || busy}
            onChange={(event) => setRecipient(event.target.value)}
          />
        </label>
        <label>
          Reply subject
          <input
            required
            value={subject}
            maxLength={1000}
            disabled={!source || busy}
            onChange={(event) => setSubject(event.target.value)}
          />
        </label>
        <label className="mail-draft-panel__wide">
          Reply body
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
          Save reply for review
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
            Provider: {draft.provider} · Recipient: {draft.recipient}
          </p>
          <p>Subject: {draft.subject}</p>
          <pre>{draft.body_text}</pre>
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
