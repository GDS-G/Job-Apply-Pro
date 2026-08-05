import type { LucideIcon } from "lucide-react";
import {
  Activity,
  Bell,
  Bot,
  BriefcaseBusiness,
  CalendarDays,
  ChevronDown,
  CircleHelp,
  FileText,
  LayoutDashboard,
  ListChecks,
  Pause,
  Play,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";

import { activity, metrics, queue } from "./sample-data";

const navigation: Array<{
  label: string;
  icon: LucideIcon;
  active?: boolean;
  badge?: string;
}> = [
  { label: "Overview", icon: LayoutDashboard, active: true },
  { label: "Discover", icon: Search },
  { label: "Workflow queue", icon: ListChecks, badge: "8" },
  { label: "Applications", icon: BriefcaseBusiness },
  { label: "Documents", icon: FileText },
  { label: "Interviews", icon: CalendarDays },
  { label: "Agents", icon: Bot },
];

const stateLabels: Record<string, string> = {
  FORM_MAPPED: "Form mapped",
  DOCUMENTS_SELECTED: "Documents ready",
  POLICY_REVIEW: "Needs policy review",
};

function AppMark() {
  return (
    <div className="app-mark" aria-label="Job Apply Pro">
      <div className="app-mark__symbol">
        <Sparkles size={19} strokeWidth={2.25} />
      </div>
      <div>
        <strong>Job Apply Pro</strong>
        <span>Core alpha</span>
      </div>
    </div>
  );
}

export function App() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="titlebar-drag" />
        <AppMark />

        <nav aria-label="Primary">
          <span className="nav-label">Workspace</span>
          {navigation.map(({ label, icon: Icon, active, badge }) => (
            <button
              className={`nav-item${active ? " nav-item--active" : ""}`}
              key={label}
              type="button"
            >
              <Icon size={18} />
              <span>{label}</span>
              {badge ? <b>{badge}</b> : null}
            </button>
          ))}
        </nav>

        <div className="sidebar__footer">
          <div className="safety-card">
            <div className="safety-card__head">
              <ShieldCheck size={18} />
              <strong>Supervised mode</strong>
            </div>
            <p>
              Submission remains locked until you review each prepared
              application.
            </p>
            <button type="button">Review safety settings</button>
          </div>
          <button className="nav-item" type="button">
            <CircleHelp size={18} />
            <span>Help & documentation</span>
          </button>
          <button className="nav-item" type="button">
            <Settings size={18} />
            <span>Settings</span>
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="titlebar-drag" />
          <div className="search-box">
            <Search size={17} />
            <span>Search applications, companies, or events</span>
            <kbd>Ctrl K</kbd>
          </div>
          <div className="topbar__actions">
            <button
              className="icon-button"
              aria-label="Notifications"
              type="button"
            >
              <Bell size={18} />
              <i />
            </button>
            <button className="profile-button" type="button">
              <span className="profile-avatar">
                <UserRound size={17} />
              </span>
              <span>
                <strong>Michael</strong>
                <small>Local workspace</small>
              </span>
              <ChevronDown size={15} />
            </button>
          </div>
        </header>

        <div className="workspace">
          <section className="hero-row">
            <div>
              <span className="eyebrow">Wednesday, August 5</span>
              <h1>Good morning, Michael.</h1>
              <p>
                Your workspace is ready. Review the prepared queue before
                starting a supervised run.
              </p>
            </div>
            <div className="hero-actions">
              <button className="button button--secondary" type="button">
                <Pause size={17} /> Pause all
              </button>
              <button className="button button--primary" type="button">
                <Play size={17} fill="currentColor" /> Start discovery
              </button>
            </div>
          </section>

          <section className="foundation-banner">
            <span className="foundation-banner__icon">
              <Sparkles size={20} />
            </span>
            <div>
              <strong>Core v0.2.0-alpha.1</strong>
              <p>
                This preview uses simulated activity. Live accounts and
                production submission are intentionally disabled.
              </p>
            </div>
            <span className="status-pill status-pill--safe">
              Local & private
            </span>
          </section>

          <section className="metrics-grid" aria-label="Application metrics">
            {metrics.map((metric) => (
              <article className="metric-card" key={metric.label}>
                <div
                  className={`metric-card__icon metric-card__icon--${metric.tone}`}
                >
                  {metric.tone === "emerald" ? (
                    <ShieldCheck />
                  ) : metric.tone === "amber" ? (
                    <ListChecks />
                  ) : metric.tone === "slate" ? (
                    <CalendarDays />
                  ) : (
                    <BriefcaseBusiness />
                  )}
                </div>
                <span>{metric.label}</span>
                <strong>{metric.value}</strong>
                <small>{metric.delta}</small>
              </article>
            ))}
          </section>

          <section className="content-grid">
            <article className="panel panel--queue">
              <div className="panel__header">
                <div>
                  <h2>Active workflow queue</h2>
                  <p>Prepared and simulated application activity</p>
                </div>
                <button className="text-button" type="button">
                  View all
                </button>
              </div>
              <div className="queue-list">
                {queue.map((item) => (
                  <div className="queue-item" key={item.id}>
                    <div className="company-logo">
                      {item.employer.slice(0, 1)}
                    </div>
                    <div className="queue-item__identity">
                      <strong>{item.role}</strong>
                      <span>
                        {item.employer} · {item.id}
                      </span>
                    </div>
                    <div className="queue-item__state">
                      <span>{stateLabels[item.state] ?? item.state}</span>
                      <small>{item.mode}</small>
                    </div>
                    <div
                      className="progress"
                      aria-label={`${item.progress}% complete`}
                    >
                      <span style={{ width: `${item.progress}%` }} />
                    </div>
                    <b className="progress-value">{item.progress}%</b>
                    <button
                      className="queue-action"
                      aria-label={`Open ${item.role}`}
                      type="button"
                    >
                      •••
                    </button>
                  </div>
                ))}
              </div>
              <div className="queue-summary">
                <span>
                  <i className="dot dot--running" /> 3 active
                </span>
                <span>
                  <i className="dot dot--waiting" /> 5 awaiting review
                </span>
                <span>
                  <i className="dot dot--paused" /> Production actions locked
                </span>
              </div>
            </article>

            <article className="panel panel--activity">
              <div className="panel__header">
                <div>
                  <h2>Recent activity</h2>
                  <p>Evidence-backed workflow events</p>
                </div>
                <Activity size={19} />
              </div>
              <div className="activity-list">
                {activity.map((item) => (
                  <div className="activity-item" key={item.id}>
                    <span
                      className={`activity-item__icon activity-item__icon--${item.severity}`}
                    >
                      {item.severity === "success" ? (
                        <ShieldCheck size={16} />
                      ) : item.severity === "warning" ? (
                        <Pause size={16} />
                      ) : (
                        <Search size={16} />
                      )}
                    </span>
                    <div>
                      <strong>{item.title}</strong>
                      <p>{item.detail}</p>
                      <small>{item.occurred_at}</small>
                    </div>
                  </div>
                ))}
              </div>
              <button className="activity-footer" type="button">
                Open audit timeline
              </button>
            </article>
          </section>
        </div>
      </main>
    </div>
  );
}
