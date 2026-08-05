import type {
  ActivityItem,
  DashboardMetric,
  QueueItem,
} from "@job-apply-pro/contracts";

export const metrics: DashboardMetric[] = [
  {
    label: "Qualified roles",
    value: 34,
    delta: "+12 this week",
    tone: "indigo",
  },
  {
    label: "Ready to review",
    value: 8,
    delta: "3 high priority",
    tone: "amber",
  },
  { label: "Confirmed", value: 17, delta: "71% completion", tone: "emerald" },
  { label: "Interviews", value: 4, delta: "+2 this month", tone: "slate" },
];

export const queue: QueueItem[] = [
  {
    id: "wf-1042",
    employer: "Northstar Systems",
    role: "Senior Platform Engineer",
    state: "FORM_MAPPED",
    progress: 64,
    mode: "Supervised",
  },
  {
    id: "wf-1041",
    employer: "Luma Health",
    role: "Staff Software Engineer",
    state: "DOCUMENTS_SELECTED",
    progress: 42,
    mode: "Supervised",
  },
  {
    id: "wf-1039",
    employer: "Aperture Finance",
    role: "Cloud Infrastructure Lead",
    state: "POLICY_REVIEW",
    progress: 81,
    mode: "Autonomous",
  },
];

export const activity: ActivityItem[] = [
  {
    id: "evt-1",
    title: "Resume matched",
    detail: "Platform Engineering resume selected with 93% evidence coverage.",
    occurred_at: "2 min ago",
    severity: "success",
  },
  {
    id: "evt-2",
    title: "Review checkpoint",
    detail:
      "Compensation answer needs approval before the workflow can continue.",
    occurred_at: "11 min ago",
    severity: "warning",
  },
  {
    id: "evt-3",
    title: "Discovery run complete",
    detail:
      "86 postings normalized; 11 duplicates and 41 policy exclusions removed.",
    occurred_at: "28 min ago",
    severity: "info",
  },
];
