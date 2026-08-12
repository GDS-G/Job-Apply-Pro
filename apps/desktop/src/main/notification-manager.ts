import { createHash } from "node:crypto";

import type {
  BackupManifest,
  ChallengeSessionSnapshot,
  CommunicationRecord,
  DesktopNotificationItem,
  DesktopNotificationKind,
  DesktopNotificationStatus,
  DesktopUpdateStatus,
  FollowUp,
  SyncedCalendarEvent,
  WorkflowRunSnapshot,
  WorkflowState,
} from "@job-apply-pro/contracts";

const POLL_INTERVAL_MS = 60_000;
const MAX_ACTIVE_NOTIFICATIONS = 50;
const MAX_NATIVE_DELIVERIES_PER_REFRESH = 5;
const MAX_DELIVERED_IDS = 500;

export interface NotificationSourceSnapshot {
  workflows: WorkflowRunSnapshot[];
  challenges: ChallengeSessionSnapshot[];
  communications: CommunicationRecord[];
  followUps: FollowUp[];
  calendarEvents: SyncedCalendarEvent[];
  backups: BackupManifest[];
  updateStatus: DesktopUpdateStatus;
}

export interface NotificationPersistentState {
  native_enabled: boolean;
  delivered_ids: string[];
}

export interface NotificationStateStore {
  load(): Promise<NotificationPersistentState>;
  save(state: NotificationPersistentState): Promise<void>;
}

export interface NativeNotificationPresenter {
  isSupported(): boolean;
  show(item: DesktopNotificationItem, onActivate: () => void): void;
}

type NotificationStatusListener = (status: DesktopNotificationStatus) => void;

const workflowNotifications: Partial<
  Record<
    WorkflowState,
    {
      kind: DesktopNotificationKind;
      title: string;
      destination: DesktopNotificationItem["destination"];
      severity: DesktopNotificationItem["severity"];
    }
  >
> = {
  MFA_REQUIRED: {
    kind: "MFA_REQUIRED",
    title: "Sign-in verification required",
    destination: "WORKFLOWS",
    severity: "warning",
  },
  CAPTCHA_REQUIRED: {
    kind: "CAPTCHA_REQUIRED",
    title: "CAPTCHA requires your attention",
    destination: "CHALLENGES",
    severity: "warning",
  },
  UNKNOWN_QUESTION: {
    kind: "USER_ACTION_REQUIRED",
    title: "Application answer needs review",
    destination: "WORKFLOWS",
    severity: "warning",
  },
  SENSITIVE_FIELD: {
    kind: "USER_ACTION_REQUIRED",
    title: "Sensitive field needs review",
    destination: "WORKFLOWS",
    severity: "warning",
  },
  POLICY_REVIEW: {
    kind: "USER_ACTION_REQUIRED",
    title: "Application policy review required",
    destination: "WORKFLOWS",
    severity: "warning",
  },
  USER_TAKEOVER: {
    kind: "USER_ACTION_REQUIRED",
    title: "Application is waiting for you",
    destination: "WORKFLOWS",
    severity: "warning",
  },
  ASSESSMENT_REQUIRED: {
    kind: "ASSESSMENT_REQUIRED",
    title: "Assessment requires your attention",
    destination: "CHALLENGES",
    severity: "warning",
  },
  SESSION_EXPIRED: {
    kind: "SESSION_EXPIRED",
    title: "Application session expired",
    destination: "WORKFLOWS",
    severity: "warning",
  },
  SUBMISSION_UNCERTAIN: {
    kind: "USER_ACTION_REQUIRED",
    title: "Submission result needs verification",
    destination: "WORKFLOWS",
    severity: "critical",
  },
  FAILED_RETRYABLE: {
    kind: "WORKFLOW_FAILED",
    title: "Application workflow can be retried",
    destination: "WORKFLOWS",
    severity: "warning",
  },
  FAILED_TERMINAL: {
    kind: "WORKFLOW_FAILED",
    title: "Application workflow stopped",
    destination: "WORKFLOWS",
    severity: "critical",
  },
};

function item(
  id: string,
  kind: DesktopNotificationKind,
  title: string,
  destination: DesktopNotificationItem["destination"],
  severity: DesktopNotificationItem["severity"],
  occurredAt: string,
  body = "Open Job Apply Pro to review the protected local details.",
): DesktopNotificationItem {
  return {
    id,
    kind,
    title,
    body,
    destination,
    severity,
    occurred_at: occurredAt,
  };
}

export function collectDesktopNotifications(
  snapshot: NotificationSourceSnapshot,
  now = new Date(),
): DesktopNotificationItem[] {
  const notifications: DesktopNotificationItem[] = [];
  const actionableChallengeStatuses = new Set([
    "INTERVENTION_REQUIRED",
    "IN_PROGRESS",
    "REVIEW_REQUIRED",
    "FAILED",
    "EXPIRED",
  ]);
  const challengeWorkflowIds = new Set(
    snapshot.challenges
      .filter((challenge) => actionableChallengeStatuses.has(challenge.status))
      .map((challenge) => challenge.workflow_id),
  );

  for (const workflow of snapshot.workflows) {
    const definition = workflowNotifications[workflow.state];
    if (!definition) continue;
    if (
      definition.destination === "CHALLENGES" &&
      challengeWorkflowIds.has(workflow.workflow_id)
    ) {
      continue;
    }
    notifications.push(
      item(
        `workflow:${workflow.workflow_id}:${workflow.state}:${workflow.updated_at}`,
        definition.kind,
        definition.title,
        definition.destination,
        definition.severity,
        workflow.updated_at,
      ),
    );
  }

  for (const challenge of snapshot.challenges) {
    const secondsRemaining = challenge.remaining_seconds;
    if (
      secondsRemaining !== null &&
      secondsRemaining !== undefined &&
      secondsRemaining > 0
    ) {
      const assessment = ["ASSESSMENT", "QUIZ"].includes(
        challenge.detection.kind,
      );
      const deadlineSeconds = assessment ? 15 * 60 : 5 * 60;
      if (secondsRemaining <= deadlineSeconds) {
        notifications.push(
          item(
            `challenge:${challenge.id}:deadline:${challenge.updated_at}`,
            assessment ? "ASSESSMENT_REQUIRED" : "SESSION_EXPIRING",
            assessment
              ? "Assessment deadline is approaching"
              : "Challenge session expires soon",
            "CHALLENGES",
            "critical",
            challenge.updated_at,
          ),
        );
      }
    }
    if (!actionableChallengeStatuses.has(challenge.status)) continue;
    const expired = challenge.status === "EXPIRED";
    const failed = challenge.status === "FAILED";
    const captcha = challenge.detection.kind === "CAPTCHA";
    const assessment = ["ASSESSMENT", "QUIZ"].includes(
      challenge.detection.kind,
    );
    notifications.push(
      item(
        `challenge:${challenge.id}:${challenge.status}:${challenge.updated_at}`,
        expired
          ? "SESSION_EXPIRED"
          : captcha
            ? "CAPTCHA_REQUIRED"
            : assessment
              ? "ASSESSMENT_REQUIRED"
              : "USER_ACTION_REQUIRED",
        expired
          ? "Challenge session expired"
          : failed
            ? "Challenge could not be completed"
            : captcha
              ? "CAPTCHA requires your attention"
              : assessment
                ? "Assessment requires your attention"
                : "Challenge needs your review",
        "CHALLENGES",
        failed ? "critical" : "warning",
        challenge.updated_at,
      ),
    );
  }

  const communicationKinds: Partial<
    Record<
      CommunicationRecord["analysis"]["classification"]["category"],
      [DesktopNotificationKind, string, DesktopNotificationItem["severity"]]
    >
  > = {
    RECRUITER_INQUIRY: [
      "RECRUITER_RESPONSE",
      "Recruiter response received",
      "info",
    ],
    INTERVIEW_REQUEST: [
      "INTERVIEW_REQUEST",
      "Interview request received",
      "warning",
    ],
    SCREENING_REQUEST: [
      "INTERVIEW_REQUEST",
      "Screening request received",
      "warning",
    ],
    ASSESSMENT_INVITATION: [
      "ASSESSMENT_REQUIRED",
      "Assessment invitation received",
      "warning",
    ],
    OFFER: ["OFFER_RECEIVED", "Offer received", "warning"],
  };
  for (const record of snapshot.communications) {
    const definition =
      communicationKinds[record.analysis.classification.category];
    if (!definition) continue;
    notifications.push(
      item(
        `communication:${record.id}:${record.analysis.classification.category}`,
        definition[0],
        definition[1],
        "COMMUNICATIONS",
        definition[2],
        record.received_at,
      ),
    );
  }

  for (const followUp of snapshot.followUps) {
    if (followUp.status !== "DUE") continue;
    notifications.push(
      item(
        `follow-up:${followUp.id}:${followUp.due_at}`,
        "FOLLOW_UP_DUE",
        "Follow-up is due",
        "COMMUNICATIONS",
        "warning",
        followUp.due_at,
      ),
    );
  }

  const interviewSignal =
    /\b(interview|phone screen|technical screen|recruiter (?:call|screen)|hiring manager)\b/i;
  for (const calendarEvent of snapshot.calendarEvents) {
    if (!interviewSignal.test(calendarEvent.event.title)) continue;
    const millisecondsUntilStart =
      Date.parse(calendarEvent.event.start_at) - now.getTime();
    if (
      millisecondsUntilStart <= 0 ||
      millisecondsUntilStart > 24 * 60 * 60 * 1_000
    ) {
      continue;
    }
    const withinOneHour = millisecondsUntilStart <= 60 * 60 * 1_000;
    const eventFingerprint = createHash("sha256")
      .update(
        `${calendarEvent.provider}\0${calendarEvent.event.provider_event_id}`,
        "utf8",
      )
      .digest("hex");
    notifications.push(
      item(
        `calendar:${eventFingerprint}:${withinOneHour ? "1h" : "24h"}`,
        "INTERVIEW_REMINDER",
        withinOneHour
          ? "Interview starts within one hour"
          : "Interview is coming up",
        "COMMUNICATIONS",
        withinOneHour ? "warning" : "info",
        calendarEvent.synced_at,
      ),
    );
  }

  for (const backup of snapshot.backups) {
    if (backup.status !== "FAILED") continue;
    notifications.push(
      item(
        `backup:${backup.id}:FAILED`,
        "BACKUP_FAILED",
        "Encrypted backup failed",
        "OPERATIONS",
        "critical",
        backup.created_at,
      ),
    );
  }

  if (snapshot.updateStatus.state === "ERROR") {
    notifications.push(
      item(
        `update:ERROR:${snapshot.updateStatus.checked_at}`,
        "UPDATE_FAILED",
        "Application update check failed",
        "OPERATIONS",
        "warning",
        snapshot.updateStatus.checked_at,
      ),
    );
  }

  return notifications
    .sort(
      (left, right) =>
        Date.parse(right.occurred_at) - Date.parse(left.occurred_at),
    )
    .slice(0, MAX_ACTIVE_NOTIFICATIONS);
}

export class DesktopNotificationManager {
  private deliveredIds = new Set<string>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private refreshInFlight: Promise<DesktopNotificationStatus> | null = null;
  private listeners = new Set<NotificationStatusListener>();
  private current: DesktopNotificationStatus;

  constructor(
    private readonly loadSnapshot: () => Promise<NotificationSourceSnapshot>,
    private readonly store: NotificationStateStore,
    private readonly presenter: NativeNotificationPresenter,
    private readonly onActivate: (item: DesktopNotificationItem) => void,
  ) {
    this.current = {
      native_enabled: false,
      native_supported: presenter.isSupported(),
      poll_interval_seconds: POLL_INTERVAL_MS / 1_000,
      active_notifications: [],
      delivered_count: 0,
      last_checked_at: null,
      last_error: null,
    };
  }

  get status(): DesktopNotificationStatus {
    return this.current;
  }

  async initialize(): Promise<void> {
    const persisted = await this.store.load();
    this.deliveredIds = new Set(persisted.delivered_ids);
    this.update({
      native_enabled: persisted.native_enabled,
      native_supported: this.presenter.isSupported(),
    });
    this.timer ??= setInterval(() => void this.refresh(), POLL_INTERVAL_MS);
  }

  stop(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  onStatus(listener: NotificationStatusListener): () => void {
    this.listeners.add(listener);
    listener(this.current);
    return () => this.listeners.delete(listener);
  }

  async setNativeEnabled(enabled: boolean): Promise<DesktopNotificationStatus> {
    this.update({ native_enabled: enabled && this.presenter.isSupported() });
    await this.persist();
    if (this.current.native_enabled) await this.refresh();
    return this.current;
  }

  refresh(): Promise<DesktopNotificationStatus> {
    if (this.refreshInFlight !== null) return this.refreshInFlight;
    this.refreshInFlight = this.performRefresh().finally(() => {
      this.refreshInFlight = null;
    });
    return this.refreshInFlight;
  }

  private async performRefresh(): Promise<DesktopNotificationStatus> {
    try {
      const active = collectDesktopNotifications(await this.loadSnapshot());
      let delivered = 0;
      if (this.current.native_enabled && this.presenter.isSupported()) {
        for (const notification of active) {
          if (
            this.deliveredIds.has(notification.id) ||
            delivered >= MAX_NATIVE_DELIVERIES_PER_REFRESH
          ) {
            continue;
          }
          this.presenter.show(notification, () =>
            this.onActivate(notification),
          );
          this.deliveredIds.add(notification.id);
          delivered += 1;
        }
      }
      if (delivered > 0) await this.persist();
      this.update({
        active_notifications: active,
        delivered_count: this.deliveredIds.size,
        last_checked_at: new Date().toISOString(),
        last_error: null,
      });
    } catch {
      this.update({
        last_checked_at: new Date().toISOString(),
        last_error:
          "Notifications could not refresh from the protected local workspace.",
      });
    }
    return this.current;
  }

  private async persist(): Promise<void> {
    const deliveredIds = [...this.deliveredIds].slice(-MAX_DELIVERED_IDS);
    this.deliveredIds = new Set(deliveredIds);
    await this.store.save({
      native_enabled: this.current.native_enabled,
      delivered_ids: deliveredIds,
    });
  }

  private update(changes: Partial<DesktopNotificationStatus>): void {
    this.current = { ...this.current, ...changes };
    for (const listener of this.listeners) listener(this.current);
  }
}
