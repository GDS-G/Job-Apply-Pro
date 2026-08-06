import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  BriefcaseBusiness,
  Check,
  CircleStop,
  FileText,
  Gauge,
  LayoutDashboard,
  ListChecks,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Upload,
  UserRound,
  X,
} from "lucide-react";

import type {
  BackendRuntimeStatus,
  BrowserSessionSnapshot,
  CandidateKnowledgeSnapshot,
  CandidateProfile,
  WorkflowControlAction,
  WorkflowRunSnapshot,
} from "@job-apply-pro/contracts";

const initialStatus: BackendRuntimeStatus = {
  state: "starting",
  message: "Connecting to the encrypted local backend…",
  checked_at: new Date(0).toISOString(),
};

const stateLabels: Record<string, string> = {
  DISCOVERED: "Discovered",
  DEDUPLICATED: "Identity checked",
  SCORED: "Fit scored",
  ELIGIBILITY_CHECKED: "Eligibility checked",
  DOCUMENTS_SELECTED: "Documents selected",
  APPLICATION_OPENED: "Application opened",
  FORM_MAPPED: "Form mapped",
  ANSWERS_VALIDATED: "Answers validated",
  READY_TO_SUBMIT: "Ready for review",
  USER_TAKEOVER: "Paused for takeover",
  FAILED_RETRYABLE: "Retry available",
  FAILED_TERMINAL: "Stopped",
  CLOSED: "Closed",
};

function readableError(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "The local operation failed unexpectedly.";
}

function AppMark() {
  return (
    <div className="app-mark" aria-label="Job Apply Pro">
      <div className="app-mark__symbol">
        <Sparkles size={19} strokeWidth={2.25} />
      </div>
      <div>
        <strong>Job Apply Pro</strong>
        <span>AI Gateway alpha</span>
      </div>
    </div>
  );
}

export function App() {
  const [status, setStatus] = useState(initialStatus);
  const [workflows, setWorkflows] = useState<WorkflowRunSnapshot[]>([]);
  const [browserSessions, setBrowserSessions] = useState<
    BrowserSessionSnapshot[]
  >([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [profile, setProfile] = useState<CandidateProfile | null>(null);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [knowledge, setKnowledge] = useState<CandidateKnowledgeSnapshot | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected =
    workflows.find((workflow) => workflow.workflow_id === selectedId) ??
    workflows[0] ??
    null;

  const refreshWorkflows = useCallback(async () => {
    try {
      const [items, sessions] = await Promise.all([
        window.jobApplyPro.workbench.listWorkflows(),
        window.jobApplyPro.workbench.listBrowserSessions(),
      ]);
      setWorkflows(items);
      setBrowserSessions(sessions);
      const first = items[0];
      if (first) {
        setSelectedId((current) => current ?? first.workflow_id);
        setProfileId((current) => current ?? first.profile_id);
      }
      setError(null);
    } catch (caught) {
      setError(readableError(caught));
    }
  }, []);

  const refreshKnowledge = useCallback(async (targetProfileId: string) => {
    try {
      const snapshot =
        await window.jobApplyPro.workbench.getCandidateKnowledge(
          targetProfileId,
        );
      setKnowledge(snapshot);
    } catch (caught) {
      setError(readableError(caught));
    }
  }, []);

  useEffect(() => {
    let active = true;
    void window.jobApplyPro.workbench.getStatus().then((next) => {
      if (active) setStatus(next);
      if (next.state === "ready") void refreshWorkflows();
    });
    const unsubscribe = window.jobApplyPro.workbench.onStatus((next) => {
      if (!active) return;
      setStatus(next);
      if (next.state === "ready") void refreshWorkflows();
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [refreshWorkflows]);

  useEffect(() => {
    if (status.state !== "ready") return;
    const timer = window.setInterval(() => void refreshWorkflows(), 2_000);
    return () => window.clearInterval(timer);
  }, [refreshWorkflows, status.state]);

  useEffect(() => {
    if (status.state === "ready" && profileId) {
      void refreshKnowledge(profileId);
    }
  }, [profileId, refreshKnowledge, status.state]);

  const metrics = useMemo(() => {
    const activeBrowsers = browserSessions.filter((item) =>
      ["ACTIVE", "USER_TAKEOVER"].includes(item.state),
    ).length;
    const proposedClaims =
      knowledge?.claims.filter(
        (claim) => claim.verification_status === "PROPOSED",
      ).length ?? 0;
    const active = workflows.filter(
      (item) => !["CLOSED", "FAILED_TERMINAL"].includes(item.state),
    ).length;
    return [
      {
        label: "Durable workflows",
        value: workflows.length,
        detail: "Stored in local SQLite",
      },
      { label: "Active", value: active, detail: "Supervised mock runs" },
      {
        label: "Claims to review",
        value: proposedClaims,
        detail: "Unverified facts stay locked out",
      },
      {
        label: "Browser sessions",
        value: activeBrowsers,
        detail: "Isolated & allowlisted",
      },
    ];
  }, [browserSessions, knowledge, workflows]);

  async function createProfile(form: FormData) {
    setBusy(true);
    setError(null);
    try {
      const created = await window.jobApplyPro.workbench.createCandidate({
        display_name: String(form.get("display_name")),
        contact: {
          full_name: String(form.get("full_name")),
          email: String(form.get("email")),
        },
      });
      setProfile(created);
      setProfileId(created.id);
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function startWorkflow(form: FormData) {
    if (profileId === null) return;
    setBusy(true);
    setError(null);
    try {
      const started = await window.jobApplyPro.workbench.startMockWorkflow({
        profile_id: profileId,
        employer: String(form.get("employer")),
        title: String(form.get("title")),
      });
      await refreshWorkflows();
      setSelectedId(started.workflow_id);
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function control(action: WorkflowControlAction) {
    if (selected === null) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await window.jobApplyPro.workbench.controlWorkflow(
        selected.workflow_id,
        action,
      );
      setWorkflows((current) =>
        current.map((item) =>
          item.workflow_id === updated.workflow_id ? updated : item,
        ),
      );
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function importResume() {
    if (!profileId) return;
    setBusy(true);
    setError(null);
    try {
      const snapshot =
        await window.jobApplyPro.workbench.selectAndImportResume(profileId);
      if (snapshot) setKnowledge(snapshot);
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function reviewClaim(claimId: string, approved: boolean) {
    if (!profileId) return;
    setBusy(true);
    setError(null);
    try {
      await window.jobApplyPro.workbench.reviewCandidateClaim(
        claimId,
        approved,
      );
      await refreshKnowledge(profileId);
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="titlebar-drag" />
        <AppMark />
        <nav aria-label="Primary">
          <span className="nav-label">Workspace</span>
          <button className="nav-item nav-item--active" type="button">
            <LayoutDashboard size={18} /> <span>Workbench</span>
          </button>
          <button className="nav-item" type="button">
            <ListChecks size={18} /> <span>Workflow queue</span>{" "}
            <b>{workflows.length}</b>
          </button>
          <button className="nav-item" type="button">
            <UserRound size={18} /> <span>Candidate profiles</span>
          </button>
          <button className="nav-item" type="button">
            <FileText size={18} /> <span>Documents</span>
          </button>
          <button className="nav-item" type="button">
            <Bot size={18} /> <span>Agents</span>
          </button>
        </nav>
        <div className="sidebar__footer">
          <div className="safety-card">
            <div className="safety-card__head">
              <ShieldCheck size={18} /> <strong>Supervised mode</strong>
            </div>
            <p>
              Mock workflows can advance, pause, retry, and recover. Submission
              is disabled.
            </p>
          </div>
          <button className="nav-item" type="button">
            <Settings size={18} /> <span>Settings</span>
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="titlebar-drag" />
          <div className="search-box">
            <Search size={17} />
            <span>Search durable workflows and application events</span>
            <kbd>Ctrl K</kbd>
          </div>
          <div className={`runtime-badge runtime-badge--${status.state}`}>
            <i />{" "}
            {status.state === "ready" ? "Backend connected" : status.state}
          </div>
        </header>

        <div className="workspace">
          <section className="hero-row">
            <div>
              <span className="eyebrow">Phase 6 · Governed model access</span>
              <h1>Supervised AI workbench</h1>
              <p>{status.message}</p>
            </div>
            <div className="hero-actions">
              <button
                className="button button--secondary"
                disabled={busy || selected === null}
                onClick={() =>
                  void control(
                    selected?.state === "USER_TAKEOVER" ? "RESUME" : "PAUSE",
                  )
                }
                type="button"
              >
                {selected?.state === "USER_TAKEOVER" ? (
                  <Play size={17} />
                ) : (
                  <Pause size={17} />
                )}
                {selected?.state === "USER_TAKEOVER" ? "Resume" : "Pause"}
              </button>
              <button
                className="button button--primary"
                disabled={busy || selected === null}
                onClick={() => void control("ADVANCE")}
                type="button"
              >
                <Play size={17} /> Advance mock run
              </button>
            </div>
          </section>

          <section className="foundation-banner">
            <span className="foundation-banner__icon">
              <Gauge size={20} />
            </span>
            <div>
              <strong>AI Gateway v0.6.0-alpha.1</strong>
              <p>
                Provider-independent routing, privacy policy, strict schemas,
                encrypted caching, and six bounded agent roles now sit above
                locked candidate evidence.
              </p>
            </div>
            <span className="status-pill status-pill--safe">
              Governed & supervised
            </span>
          </section>

          {error ? (
            <div className="error-banner" role="alert">
              <AlertTriangle size={17} />
              <div>
                <strong>Action needs attention</strong>
                <span>
                  {error} Your saved workflow state was not discarded.
                </span>
              </div>
              <button onClick={() => setError(null)} type="button">
                Dismiss
              </button>
            </div>
          ) : null}

          <section className="metrics-grid" aria-label="Workbench metrics">
            {metrics.map((metric, index) => (
              <article className="metric-card" key={metric.label}>
                <div
                  className={`metric-card__icon metric-card__icon--${index === 2 ? "amber" : index === 3 ? "slate" : index === 1 ? "emerald" : "indigo"}`}
                >
                  {index === 0 ? (
                    <BriefcaseBusiness />
                  ) : index === 1 ? (
                    <Activity />
                  ) : index === 2 ? (
                    <ShieldCheck />
                  ) : (
                    <Pause />
                  )}
                </div>
                <span>{metric.label}</span>
                <strong>{metric.value}</strong>
                <small>{metric.detail}</small>
              </article>
            ))}
          </section>

          <section className="content-grid">
            <article className="panel panel--queue">
              <div className="panel__header">
                <div>
                  <h2>Durable workflow queue</h2>
                  <p>
                    Refreshed from the authenticated local backend every two
                    seconds
                  </p>
                </div>
                <button
                  className="text-button"
                  onClick={() => void refreshWorkflows()}
                  type="button"
                >
                  <RefreshCw size={13} /> Refresh
                </button>
              </div>
              <div className="queue-list">
                {workflows.length === 0 ? (
                  <div className="empty-state">
                    <BriefcaseBusiness size={24} />
                    <strong>No workflows yet</strong>
                    <span>
                      Create a secure profile, then start a mock application.
                    </span>
                  </div>
                ) : (
                  workflows.map((item) => (
                    <button
                      className={`queue-item queue-item--button${selected?.workflow_id === item.workflow_id ? " queue-item--selected" : ""}`}
                      key={item.workflow_id}
                      onClick={() => setSelectedId(item.workflow_id)}
                      type="button"
                    >
                      <span className="company-logo">
                        {item.employer.slice(0, 1)}
                      </span>
                      <span className="queue-item__identity">
                        <strong>{item.title}</strong>
                        <span>
                          {item.employer} · {item.candidate_display_name}
                        </span>
                      </span>
                      <span className="queue-item__state">
                        <span>{stateLabels[item.state] ?? item.state}</span>
                        <small>{item.events.length} persisted events</small>
                      </span>
                      <span
                        className="progress"
                        aria-label={`${item.progress}% complete`}
                      >
                        <span style={{ width: `${item.progress}%` }} />
                      </span>
                      <b className="progress-value">{item.progress}%</b>
                    </button>
                  ))
                )}
              </div>
              {selected ? (
                <div className="queue-controls">
                  <button
                    disabled={busy}
                    onClick={() => void control("RETRY")}
                    type="button"
                  >
                    <RotateCcw size={14} /> Retry checkpoint
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => void control("TAKEOVER")}
                    type="button"
                  >
                    <UserRound size={14} /> Take over
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => void control("STOP")}
                    type="button"
                  >
                    <CircleStop size={14} /> Stop safely
                  </button>
                </div>
              ) : null}
            </article>

            <article className="panel setup-panel">
              <div className="panel__header">
                <div>
                  <h2>
                    {profileId
                      ? "Start a mock workflow"
                      : "Create secure profile"}
                  </h2>
                  <p>
                    {profileId
                      ? "No external portal will be contacted"
                      : "Contact data is encrypted before storage"}
                  </p>
                </div>
                <ShieldCheck size={19} />
              </div>
              {profileId ? (
                <form
                  action={(form) => void startWorkflow(form)}
                  className="workbench-form"
                >
                  <label>
                    Employer
                    <input
                      name="employer"
                      placeholder="Example Systems"
                      required
                      maxLength={200}
                    />
                  </label>
                  <label>
                    Role title
                    <input
                      name="title"
                      placeholder="Platform Engineer"
                      required
                      maxLength={200}
                    />
                  </label>
                  <div className="profile-confirmation">
                    <UserRound size={16} />
                    <span>
                      {profile?.display_name ??
                        selected?.candidate_display_name ??
                        "Recovered profile"}
                    </span>
                  </div>
                  <button
                    className="button button--primary form-submit"
                    disabled={busy || status.state !== "ready"}
                    type="submit"
                  >
                    <Play size={16} /> Start mock workflow
                  </button>
                </form>
              ) : (
                <form
                  action={(form) => void createProfile(form)}
                  className="workbench-form"
                >
                  <label>
                    Profile label
                    <input
                      name="display_name"
                      defaultValue="Primary profile"
                      required
                      maxLength={200}
                    />
                  </label>
                  <label>
                    Full name
                    <input
                      name="full_name"
                      placeholder="Your name"
                      required
                      maxLength={200}
                    />
                  </label>
                  <label>
                    Email
                    <input
                      name="email"
                      type="email"
                      placeholder="you@example.com"
                      required
                      maxLength={320}
                    />
                  </label>
                  <button
                    className="button button--primary form-submit"
                    disabled={busy || status.state !== "ready"}
                    type="submit"
                  >
                    <ShieldCheck size={16} /> Create encrypted profile
                  </button>
                </form>
              )}
            </article>
          </section>

          <section className="panel knowledge-panel">
            <div className="panel__header">
              <div>
                <h2>Candidate documents & evidence</h2>
                <p>
                  {knowledge
                    ? `${knowledge.documents.length} encrypted document variants · ${knowledge.claims.length} evidence-backed claims`
                    : "Create or select a candidate profile to begin"}
                </p>
              </div>
              <button
                className="button button--secondary"
                disabled={busy || !profileId}
                onClick={() => void importResume()}
                type="button"
              >
                <Upload size={15} /> Import resume
              </button>
            </div>
            <div className="knowledge-grid">
              <div className="document-variants">
                <strong>Resume variants</strong>
                {knowledge?.documents.length ? (
                  knowledge.documents.map((document) => (
                    <div className="knowledge-row" key={document.id}>
                      <FileText size={15} />
                      <span>
                        <b>{document.display_name}</b>
                        <small>{document.variant_label}</small>
                      </span>
                      {document.is_primary ? <em>Primary</em> : null}
                    </div>
                  ))
                ) : (
                  <div className="empty-state empty-state--compact">
                    No candidate documents imported.
                  </div>
                )}
              </div>
              <div className="claim-review">
                <strong>Manual fact review</strong>
                {knowledge?.claims.some(
                  (claim) => claim.verification_status === "PROPOSED",
                ) ? (
                  knowledge.claims
                    .filter((claim) => claim.verification_status === "PROPOSED")
                    .slice(0, 6)
                    .map((claim) => (
                      <div className="claim-row" key={claim.id}>
                        <span>
                          <b>{claim.canonical_key}</b>
                          <small>{claim.statement}</small>
                        </span>
                        <button
                          aria-label={`Approve ${claim.canonical_key}`}
                          disabled={busy}
                          onClick={() => void reviewClaim(claim.id, true)}
                          type="button"
                        >
                          <Check size={13} />
                        </button>
                        <button
                          aria-label={`Reject ${claim.canonical_key}`}
                          disabled={busy}
                          onClick={() => void reviewClaim(claim.id, false)}
                          type="button"
                        >
                          <X size={13} />
                        </button>
                      </div>
                    ))
                ) : (
                  <div className="empty-state empty-state--compact">
                    No proposed facts are waiting for review.
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="panel timeline-panel">
            <div className="panel__header">
              <div>
                <h2>Persisted event timeline</h2>
                <p>
                  {selected
                    ? `${selected.employer} · ${selected.title}`
                    : "Select a workflow to inspect its evidence"}
                </p>
              </div>
              <Activity size={19} />
            </div>
            <div className="timeline-list">
              {selected?.events.length ? (
                [...selected.events].reverse().map((event) => (
                  <div className="timeline-event" key={event.id}>
                    <span className="timeline-event__sequence">
                      {event.sequence}
                    </span>
                    <div>
                      <strong>
                        {stateLabels[event.next_state] ?? event.next_state}
                      </strong>
                      <p>{event.cause}</p>
                    </div>
                    <time>
                      {new Date(event.occurred_at).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </time>
                  </div>
                ))
              ) : (
                <div className="empty-state empty-state--compact">
                  Workflow events will appear here.
                </div>
              )}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
