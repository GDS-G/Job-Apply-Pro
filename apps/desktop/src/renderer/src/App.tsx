import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  BriefcaseBusiness,
  CalendarDays,
  Check,
  CircleStop,
  FileText,
  Gauge,
  LayoutDashboard,
  ListChecks,
  Mail,
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
  BackupManifest,
  BackupSchedule,
  BrowserSessionSnapshot,
  CandidateKnowledgeSnapshot,
  CandidateProfile,
  ChallengeAnswerSuggestion,
  ChallengeSessionSnapshot,
  CommunicationRecord,
  DailyCommunicationSummary,
  DesktopUpdateStatus,
  IntegrationHealth,
  HelpTopic,
  OperationsDashboard,
  PortalAdapterDefinition,
  PortalRunSnapshot,
  RestorePlan,
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
  SUBMISSION_ATTEMPTED: "Submission attempted",
  SUBMISSION_CONFIRMED: "Submission confirmed",
  TRACKING_ACTIVE: "Tracking active",
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
        <span>Production hardening</span>
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
  const [portalRuns, setPortalRuns] = useState<PortalRunSnapshot[]>([]);
  const [portalCatalog, setPortalCatalog] = useState<PortalAdapterDefinition[]>(
    [],
  );
  const [challengeSessions, setChallengeSessions] = useState<
    ChallengeSessionSnapshot[]
  >([]);
  const [challengeSuggestions, setChallengeSuggestions] = useState<
    ChallengeAnswerSuggestion[]
  >([]);
  const [integrationHealth, setIntegrationHealth] = useState<
    IntegrationHealth[]
  >([]);
  const [communications, setCommunications] = useState<CommunicationRecord[]>(
    [],
  );
  const [communicationSummary, setCommunicationSummary] =
    useState<DailyCommunicationSummary | null>(null);
  const [operations, setOperations] = useState<OperationsDashboard | null>(
    null,
  );
  const [backups, setBackups] = useState<BackupManifest[]>([]);
  const [backupSchedules, setBackupSchedules] = useState<BackupSchedule[]>([]);
  const [restorePlan, setRestorePlan] = useState<RestorePlan | null>(null);
  const [helpTopics, setHelpTopics] = useState<HelpTopic[]>([]);
  const [updateStatus, setUpdateStatus] = useState<DesktopUpdateStatus | null>(
    null,
  );
  const [diagnosticPath, setDiagnosticPath] = useState<string | null>(null);
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
      const [
        items,
        sessions,
        runs,
        challenges,
        adapters,
        integrations,
        records,
        summary,
        operationsSnapshot,
        backupItems,
        scheduleItems,
        topics,
        desktopUpdate,
      ] = await Promise.all([
        window.jobApplyPro.workbench.listWorkflows(),
        window.jobApplyPro.workbench.listBrowserSessions(),
        window.jobApplyPro.workbench.listPortalRuns(),
        window.jobApplyPro.workbench.listChallengeSessions(),
        window.jobApplyPro.workbench.listPortalCatalog(),
        window.jobApplyPro.workbench.listIntegrationHealth(),
        window.jobApplyPro.workbench.listCommunicationRecords(),
        window.jobApplyPro.workbench.getDailyCommunicationSummary(),
        window.jobApplyPro.workbench.getOperationsDashboard(),
        window.jobApplyPro.workbench.listBackups(),
        window.jobApplyPro.workbench.listBackupSchedules(),
        window.jobApplyPro.workbench.listHelpTopics(),
        window.jobApplyPro.workbench.getUpdateStatus(),
      ]);
      setWorkflows(items);
      setBrowserSessions(sessions);
      setPortalRuns(runs);
      setChallengeSessions(challenges);
      setPortalCatalog(adapters);
      setIntegrationHealth(integrations);
      setCommunications(records);
      setCommunicationSummary(summary);
      setOperations(operationsSnapshot);
      setBackups(backupItems);
      setBackupSchedules(scheduleItems);
      setHelpTopics(topics);
      setUpdateStatus(desktopUpdate);
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

  useEffect(
    () => window.jobApplyPro.workbench.onUpdateStatus(setUpdateStatus),
    [],
  );

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
        label: "Messages analyzed",
        value: communicationSummary?.analyzed_messages ?? 0,
        detail: `${communicationSummary?.review_required ?? 0} need review · ${activeBrowsers} browsers`,
      },
    ];
  }, [browserSessions, communicationSummary, knowledge, workflows]);

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

  async function createEncryptedBackup() {
    setBusy(true);
    setError(null);
    try {
      const backup = await window.jobApplyPro.workbench.createBackup(
        "Manual desktop backup",
      );
      setBackups((current) => [backup, ...current]);
      await refreshWorkflows();
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function verifyEncryptedBackup(backupId: string) {
    setBusy(true);
    setError(null);
    try {
      const result = await window.jobApplyPro.workbench.verifyBackup(backupId);
      if (!result.valid) {
        throw new Error(
          `Backup verification failed: ${result.reasons.join(", ")}`,
        );
      }
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function createDailyBackupSchedule() {
    setBusy(true);
    setError(null);
    try {
      const schedule = await window.jobApplyPro.workbench.createBackupSchedule(
        "Daily encrypted backup",
        24,
      );
      setBackupSchedules((current) => [schedule, ...current]);
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function stageLatestRestore(backupId: string) {
    setBusy(true);
    setError(null);
    try {
      setRestorePlan(await window.jobApplyPro.workbench.stageRestore(backupId));
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function applyStagedRestore(plan: RestorePlan) {
    setBusy(true);
    setError(null);
    try {
      const applied = await window.jobApplyPro.workbench.applyRestore(
        plan.id,
        plan.fingerprint,
      );
      if (applied) {
        setRestorePlan({
          ...plan,
          status: "APPLIED",
          applied_at: new Date().toISOString(),
        });
        await refreshWorkflows();
      }
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function exportDiagnostics() {
    setBusy(true);
    setError(null);
    try {
      setDiagnosticPath(
        await window.jobApplyPro.workbench.exportSupportDiagnostics(),
      );
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function checkForUpdates() {
    setBusy(true);
    setError(null);
    try {
      setUpdateStatus(await window.jobApplyPro.workbench.checkForUpdates());
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function downloadUpdate() {
    setBusy(true);
    setError(null);
    try {
      setUpdateStatus(await window.jobApplyPro.workbench.downloadUpdate());
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

  async function prepareReferencePortal(form: FormData) {
    if (!profileId) return;
    setBusy(true);
    setError(null);
    try {
      const run = await window.jobApplyPro.workbench.prepareReferencePortal({
        profile_id: profileId,
        portal_origin: String(form.get("portal_origin")),
        query: String(form.get("query")),
        minimum_fit_score: 0.5,
      });
      setPortalRuns((current) => [
        run,
        ...current.filter((item) => item.id !== run.id),
      ]);
      await refreshWorkflows();
      setSelectedId(run.workflow_id);
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function confirmReferencePortal(run: PortalRunSnapshot) {
    setBusy(true);
    setError(null);
    try {
      const completed =
        await window.jobApplyPro.workbench.confirmReferencePortal(
          run.id,
          run.review_fingerprint,
        );
      setPortalRuns((current) =>
        current.map((item) => (item.id === completed.id ? completed : item)),
      );
      await refreshWorkflows();
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function detectChallenge() {
    if (!selected) return;
    const browser = browserSessions.find(
      (item) => item.workflow_id === selected.workflow_id,
    );
    if (!browser) {
      setError("This workflow has no browser session to inspect.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const challenge = await window.jobApplyPro.workbench.detectChallenge({
        workflow_id: selected.workflow_id,
        browser_session_id: browser.id,
      });
      setChallengeSessions((current) => [
        challenge,
        ...current.filter((item) => item.id !== challenge.id),
      ]);
      setChallengeSuggestions(
        await window.jobApplyPro.workbench.getChallengeSuggestions(
          challenge.id,
        ),
      );
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function answerChallenge(sessionId: string, form: FormData) {
    setBusy(true);
    setError(null);
    try {
      const updated = await window.jobApplyPro.workbench.answerChallenge(
        sessionId,
        {
          question_id: String(form.get("question_id")),
          value: String(form.get("value")),
        },
      );
      setChallengeSessions((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function finishChallenge(challenge: ChallengeSessionSnapshot) {
    setBusy(true);
    setError(null);
    try {
      const updated =
        challenge.status === "INTERVENTION_REQUIRED"
          ? await window.jobApplyPro.workbench.completeChallengeIntervention(
              challenge.id,
              challenge.detection.page_fingerprint,
            )
          : await window.jobApplyPro.workbench.completeChallenge(
              challenge.id,
              challenge.review_fingerprint ?? "",
            );
      setChallengeSessions((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      await refreshWorkflows();
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  }

  const latestPortalRun = portalRuns[0] ?? null;
  const activeChallenge =
    challengeSessions.find(
      (item) => item.workflow_id === selected?.workflow_id,
    ) ?? null;

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
          <button className="nav-item" type="button">
            <Mail size={18} /> <span>Communications</span>{" "}
            <b>{communications.length}</b>
          </button>
        </nav>
        <div className="sidebar__footer">
          <div className="safety-card">
            <div className="safety-card__head">
              <ShieldCheck size={18} /> <strong>Supervised mode</strong>
            </div>
            <p>
              Production submission and provider writes are disabled. Every
              email or calendar mutation requires an exact review fingerprint.
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
              <span className="eyebrow">
                Phase 12 · Production hardening and release readiness
              </span>
              <h1>Supervised application workbench</h1>
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
              <strong>Portal Readiness v0.12.2-alpha.1</strong>
              <p>
                Bundled Windows runtime, offline recovery, redacted diagnostics,
                accessibility gates, and signed-update controls are ready for
                release validation.
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

          <section className="panel portal-panel">
            <div className="panel__header">
              <div>
                <h2>Reference ATS vertical slice</h2>
                <p>
                  Loopback fixtures only · production portal submission remains
                  locked
                </p>
              </div>
              <ShieldCheck size={19} />
            </div>
            <div className="portal-grid">
              <form
                action={(form) => void prepareReferencePortal(form)}
                className="workbench-form"
              >
                <label>
                  Fixture origin
                  <input
                    name="portal_origin"
                    defaultValue="http://127.0.0.1:4173"
                    required
                    type="url"
                  />
                </label>
                <label>
                  Job query
                  <input
                    name="query"
                    defaultValue="Python automation"
                    required
                    maxLength={200}
                  />
                </label>
                <button
                  className="button button--primary form-submit"
                  disabled={busy || !profileId || !knowledge?.documents.length}
                  type="submit"
                >
                  <Play size={16} /> Prepare verified application
                </button>
              </form>
              <div className="portal-status">
                {latestPortalRun ? (
                  <>
                    <span className="status-pill status-pill--safe">
                      {stateLabels[latestPortalRun.state] ??
                        latestPortalRun.state}
                    </span>
                    <strong>
                      Fit{" "}
                      {Math.round(latestPortalRun.qualification.score * 100)}%
                    </strong>
                    <p>
                      {latestPortalRun.field_mappings.length} canonical fields ·{" "}
                      {latestPortalRun.deduplicated
                        ? "existing job reused"
                        : "new job recorded"}
                    </p>
                    {latestPortalRun.submission_evidence ? (
                      <small>
                        Confirmation{" "}
                        {latestPortalRun.submission_evidence.confirmation_code}
                      </small>
                    ) : null}
                    {latestPortalRun.state === "READY_TO_SUBMIT" ? (
                      <button
                        className="button button--primary"
                        disabled={busy}
                        onClick={() =>
                          void confirmReferencePortal(latestPortalRun)
                        }
                        type="button"
                      >
                        <ShieldCheck size={16} /> Confirm fixture submission
                      </button>
                    ) : null}
                  </>
                ) : (
                  <div className="empty-state empty-state--compact">
                    Import and approve a resume, then provide a running
                    reference ATS fixture origin.
                  </div>
                )}
              </div>
            </div>
            <div
              className="adapter-health"
              aria-label="Portal adapter health"
              role="region"
            >
              {portalCatalog.map((adapter) => (
                <div className="adapter-health__item" key={adapter.kind}>
                  <div>
                    <strong>{adapter.display_name}</strong>
                    <small>{adapter.strategy.replaceAll("_", " ")}</small>
                  </div>
                  <span className="status-pill status-pill--safe">
                    {adapter.support_status.replaceAll("_", " ")}
                  </span>
                  <small>
                    {adapter.replay_validated_page_types.length} replay page
                    types · {adapter.live_validated_page_types.length} live ·
                    production off
                  </small>
                </div>
              ))}
            </div>
          </section>

          <section className="panel challenge-panel">
            <div className="panel__header">
              <div>
                <h2>Challenge framework</h2>
                <p>
                  CAPTCHA intervention, questionnaires, and timed assessments
                </p>
              </div>
              <ListChecks size={19} />
            </div>
            <div className="challenge-workspace">
              <div className="challenge-summary">
                {activeChallenge ? (
                  <>
                    <span className="status-pill status-pill--safe">
                      {activeChallenge.detection.kind} ·{" "}
                      {activeChallenge.status}
                    </span>
                    <strong>
                      {activeChallenge.questions.length} detected questions
                    </strong>
                    <p>
                      {activeChallenge.remaining_seconds == null
                        ? "No visible timer"
                        : `${activeChallenge.remaining_seconds}s remaining`}
                    </p>
                    {activeChallenge.status === "INTERVENTION_REQUIRED" ? (
                      <button
                        className="button button--primary"
                        disabled={busy}
                        onClick={() => void finishChallenge(activeChallenge)}
                        type="button"
                      >
                        <ShieldCheck size={16} /> I completed the CAPTCHA
                      </button>
                    ) : null}
                    {activeChallenge.status === "REVIEW_REQUIRED" ? (
                      <button
                        className="button button--primary"
                        disabled={busy}
                        onClick={() => void finishChallenge(activeChallenge)}
                        type="button"
                      >
                        <ShieldCheck size={16} /> Confirm challenge completion
                      </button>
                    ) : null}
                  </>
                ) : (
                  <>
                    <p>
                      Inspect the selected workflow’s active browser page and
                      create a durable challenge checkpoint.
                    </p>
                    <button
                      className="button button--primary"
                      disabled={busy || !selected}
                      onClick={() => void detectChallenge()}
                      type="button"
                    >
                      <Search size={16} /> Detect challenge
                    </button>
                  </>
                )}
              </div>
              <div className="challenge-questions">
                {activeChallenge?.questions.map((question) => {
                  const answer = activeChallenge.answers.find(
                    (item) => item.question_id === question.id,
                  );
                  const suggestion = challengeSuggestions.find(
                    (item) => item.question_id === question.id,
                  );
                  return (
                    <form
                      action={(form) =>
                        void answerChallenge(activeChallenge.id, form)
                      }
                      className="challenge-question"
                      key={question.id}
                    >
                      <input
                        name="question_id"
                        type="hidden"
                        value={question.id}
                      />
                      <label>
                        {question.prompt}
                        {question.required ? " *" : ""}
                        {question.options.length ? (
                          <select
                            defaultValue={
                              answer?.value ?? suggestion?.value ?? ""
                            }
                            disabled={
                              busy ||
                              question.legal_attestation ||
                              question.signature_required
                            }
                            name="value"
                          >
                            <option value="">Choose an answer</option>
                            {question.options.filter(Boolean).map((option) => (
                              <option key={option} value={option}>
                                {option}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <input
                            defaultValue={
                              answer?.value ?? suggestion?.value ?? ""
                            }
                            disabled={
                              busy ||
                              question.legal_attestation ||
                              question.signature_required
                            }
                            maxLength={question.character_limit ?? undefined}
                            name="value"
                          />
                        )}
                      </label>
                      {question.legal_attestation ||
                      question.signature_required ? (
                        <small>
                          Direct user action is required for this field.
                        </small>
                      ) : (
                        <button
                          className="button button--secondary"
                          disabled={busy}
                          type="submit"
                        >
                          <Check size={14} /> Verify answer
                        </button>
                      )}
                    </form>
                  );
                }) ?? (
                  <div className="empty-state empty-state--compact">
                    Challenge questions and verified answers will appear here.
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="panel operations-panel">
            <div className="panel__header">
              <div>
                <h2>Operations, recovery & licensing</h2>
                <p>
                  Audit-reconciled reports, model cost, encrypted backups, and
                  recovery-safe entitlement status
                </p>
              </div>
              <ShieldCheck size={19} />
            </div>
            <div className="operations-grid">
              <article className="operations-card">
                <span>Confirmed / attempted</span>
                <strong>
                  {operations?.applications.submission_confirmed ?? 0} /{" "}
                  {operations?.applications.submission_attempted ?? 0}
                </strong>
                <small>
                  Attempts never count as independently confirmed submissions.
                </small>
              </article>
              <article className="operations-card">
                <span>Interviews / offers</span>
                <strong>
                  {operations?.applications.interviews_received ?? 0} /{" "}
                  {operations?.applications.offers_received ?? 0}
                </strong>
                <small>Derived from correlated encrypted communications.</small>
              </article>
              <article className="operations-card">
                <span>Model cost</span>
                <strong>
                  $
                  {((operations?.models.cost_micros ?? 0) / 1_000_000).toFixed(
                    4,
                  )}
                </strong>
                <small>
                  {operations?.models.input_tokens ?? 0} input ·{" "}
                  {operations?.models.output_tokens ?? 0} output tokens
                </small>
              </article>
              <article className="operations-card">
                <span>License</span>
                <strong>{operations?.license.status ?? "LOADING"}</strong>
                <small>
                  Recovery allowed:{" "}
                  {operations?.license.recovery_allowed ? "yes" : "no"}
                </small>
              </article>
              <article className="operations-card">
                <span>Secure updates</span>
                <strong>{updateStatus?.state ?? "LOADING"}</strong>
                <small>
                  {updateStatus?.message ?? "Reading update status…"}
                </small>
              </article>
            </div>
            <div className="backup-workspace">
              <div>
                <strong>Encrypted local backups</strong>
                <p>
                  Outer-encrypted archives include a versioned manifest and
                  per-entry SHA-256 integrity hashes.
                </p>
                <div className="hero-actions">
                  <button
                    className="button button--primary"
                    disabled={busy}
                    onClick={() => void createEncryptedBackup()}
                    type="button"
                  >
                    <ShieldCheck size={15} /> Create verified backup
                  </button>
                  <button
                    className="button button--secondary"
                    disabled={busy || backups.length === 0}
                    onClick={() =>
                      backups[0] && void verifyEncryptedBackup(backups[0].id)
                    }
                    type="button"
                  >
                    <Check size={15} /> Verify latest
                  </button>
                  <button
                    className="button button--secondary"
                    disabled={busy || backups.length === 0}
                    onClick={() =>
                      backups[0] && void stageLatestRestore(backups[0].id)
                    }
                    type="button"
                  >
                    <RotateCcw size={15} /> Stage restore
                  </button>
                  {restorePlan?.status === "STAGED" && (
                    <button
                      className="button button--danger"
                      disabled={busy}
                      onClick={() => void applyStagedRestore(restorePlan)}
                      type="button"
                    >
                      <ShieldCheck size={15} /> Apply staged restore
                    </button>
                  )}
                  <button
                    className="button button--secondary"
                    disabled={busy || backupSchedules.length > 0}
                    onClick={() => void createDailyBackupSchedule()}
                    type="button"
                  >
                    <CalendarDays size={15} /> Schedule daily
                  </button>
                  <button
                    className="button button--secondary"
                    disabled={busy}
                    onClick={() => void exportDiagnostics()}
                    type="button"
                  >
                    <FileText size={15} /> Export diagnostics
                  </button>
                  <button
                    className="button button--secondary"
                    disabled={busy || updateStatus?.state === "DISABLED"}
                    onClick={() => void checkForUpdates()}
                    type="button"
                  >
                    <RefreshCw size={15} /> Check for updates
                  </button>
                  {updateStatus?.state === "AVAILABLE" && (
                    <button
                      className="button button--secondary"
                      disabled={busy}
                      onClick={() => void downloadUpdate()}
                      type="button"
                    >
                      <Upload size={15} /> Download update
                    </button>
                  )}
                  {updateStatus?.state === "DOWNLOADED" && (
                    <button
                      className="button button--primary"
                      disabled={busy}
                      onClick={() =>
                        void window.jobApplyPro.workbench.installUpdate()
                      }
                      type="button"
                    >
                      <RotateCcw size={15} /> Restart and install
                    </button>
                  )}
                </div>
              </div>
              <div className="backup-status">
                {backups[0] ? (
                  <>
                    <span className="status-pill status-pill--safe">
                      {backups[0].status}
                    </span>
                    <strong>{backups[0].label}</strong>
                    <small>
                      {backups[0].entries.length} entries ·{" "}
                      {(backups[0].archive_size_bytes / 1024).toFixed(1)} KiB ·
                      schema {backups[0].schema_revision}
                    </small>
                    <small>
                      {backupSchedules[0]
                        ? `Next scheduled backup: ${new Date(
                            backupSchedules[0].next_run_at,
                          ).toLocaleString()}`
                        : "No automatic backup schedule is configured."}
                    </small>
                    {restorePlan && (
                      <small>
                        Restore {restorePlan.status.toLowerCase()}:{" "}
                        {restorePlan.file_count} files · fingerprint{" "}
                        {restorePlan.fingerprint.slice(0, 12)}…
                      </small>
                    )}
                    {diagnosticPath && (
                      <small>
                        Redacted diagnostics saved to {diagnosticPath}
                      </small>
                    )}
                  </>
                ) : (
                  <small>No local backup has been created yet.</small>
                )}
              </div>
            </div>
            <div className="operations-reports">
              <article>
                <strong>Application report</strong>
                <div className="operations-report-list">
                  {operations?.application_report.slice(0, 5).map((row) => (
                    <div key={row.workflow_id}>
                      <span>
                        {row.employer} · {row.title}
                      </span>
                      <small>
                        {row.state} · attempted{" "}
                        {row.submission_attempted ? "yes" : "no"} · confirmed{" "}
                        {row.submission_confirmed ? "yes" : "no"}
                      </small>
                    </div>
                  )) ?? null}
                  {operations?.application_report.length === 0 && (
                    <small>
                      No application evidence has been recorded yet.
                    </small>
                  )}
                </div>
              </article>
              <article>
                <strong>Interview and recruiter report</strong>
                <div className="operations-report-list">
                  {operations?.interview_report.slice(0, 5).map((row) => (
                    <div key={row.communication_id}>
                      <span>{row.subject}</span>
                      <small>
                        {row.category} · {row.sender} ·{" "}
                        {new Date(row.received_at).toLocaleDateString()}
                      </small>
                    </div>
                  )) ?? null}
                  {operations?.interview_report.length === 0 && (
                    <small>
                      No correlated recruiter activity has been recorded yet.
                    </small>
                  )}
                </div>
              </article>
            </div>
            <div className="help-grid">
              {helpTopics.slice(0, 4).map((topic) => (
                <article key={topic.id}>
                  <strong>{topic.title}</strong>
                  <small>{topic.summary}</small>
                </article>
              ))}
            </div>
          </section>

          <section className="panel communications-panel">
            <div className="panel__header">
              <div>
                <h2>Communication & scheduling</h2>
                <p>
                  Encrypted message correlation, review-only replies, provider
                  health, and audited calendar changes
                </p>
              </div>
              <Mail size={19} />
            </div>
            <div className="integration-grid">
              {integrationHealth.map((integration) => (
                <article
                  className="integration-card"
                  key={integration.provider}
                >
                  <div>
                    {integration.provider.includes("CALENDAR") ? (
                      <CalendarDays size={17} />
                    ) : (
                      <Mail size={17} />
                    )}
                    <strong>{integration.provider.replaceAll("_", " ")}</strong>
                  </div>
                  <span
                    className={`status-pill ${
                      integration.status === "CONNECTED"
                        ? "status-pill--safe"
                        : "status-pill--warning"
                    }`}
                  >
                    {integration.status.replaceAll("_", " ")}
                  </span>
                  <small>{integration.message}</small>
                </article>
              ))}
            </div>
            <div className="communication-list">
              {communications.length ? (
                communications.slice(0, 5).map((record) => (
                  <article key={record.id}>
                    <span>
                      {record.analysis.classification.category.replaceAll(
                        "_",
                        " ",
                      )}
                    </span>
                    <div>
                      <strong>{record.analysis.message.subject}</strong>
                      <small>
                        {record.analysis.correlation.workflow_id
                          ? `Matched ${record.analysis.correlation.workflow_id}`
                          : "Manual correlation review required"}
                      </small>
                    </div>
                    <time>
                      {new Date(record.received_at).toLocaleDateString()}
                    </time>
                  </article>
                ))
              ) : (
                <div className="empty-state empty-state--compact">
                  No provider messages have been imported. OAuth remains
                  disabled until credentials are configured in Settings.
                </div>
              )}
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
