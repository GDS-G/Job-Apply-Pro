import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  BackupManifest,
  ChallengeSessionSnapshot,
  CommunicationRecord,
  DesktopNotificationItem,
  FollowUp,
  SyncedCalendarEvent,
  WorkflowRunSnapshot,
} from "@job-apply-pro/contracts";

import {
  collectDesktopNotifications,
  DesktopNotificationManager,
  type NotificationPersistentState,
  type NotificationSourceSnapshot,
} from "./notification-manager.js";

function sourceSnapshot(): NotificationSourceSnapshot {
  return {
    workflows: [
      {
        workflow_id: "workflow-1",
        application_id: "application-1",
        profile_id: "profile-1",
        candidate_display_name: "Private Candidate",
        employer: "Secret Employer",
        title: "Confidential Role",
        state: "MFA_REQUIRED",
        progress: 40,
        updated_at: "2026-08-11T12:00:00Z",
        events: [],
      } satisfies WorkflowRunSnapshot,
    ],
    challenges: [],
    communications: [
      {
        id: "message-1",
        analysis: {
          message: {
            provider: "GMAIL",
            provider_message_id: "provider-message-1",
            provider_thread_id: "provider-thread-1",
            sender: "private@example.invalid",
            recipients: ["candidate@example.invalid"],
            subject: "Secret offer subject",
            body_text: "Private message body",
            received_at: "2026-08-11T13:00:00Z",
            attachment_names: [],
            referenced_identifiers: [],
            referenced_urls: [],
          },
          classification: {
            category: "OFFER",
            confidence: 1,
            matched_signals: [],
            requires_review: true,
          },
          correlation: {
            workflow_id: "workflow-1",
            confidence: 1,
            matched_signals: [],
            requires_review: false,
          },
          reply_draft: {
            subject: "Private draft",
            body_text: "Private reply",
            category: "OFFER",
            requires_review: true,
            auto_send_allowed: false,
            evidence: [],
          },
          proposed_times: [],
          time_proposal_requires_review: false,
        },
        received_at: "2026-08-11T13:00:00Z",
        created_at: "2026-08-11T13:00:00Z",
      } satisfies CommunicationRecord,
    ],
    followUps: [
      {
        id: "follow-up-1",
        workflow_id: "workflow-1",
        reason: "Private follow-up reason",
        due_at: "2026-08-11T14:00:00Z",
        channel: "GMAIL",
        status: "DUE",
        dedupe_key: "a".repeat(64),
        created_at: "2026-08-10T14:00:00Z",
        updated_at: "2026-08-11T14:00:00Z",
      } satisfies FollowUp,
    ],
    calendarEvents: [],
    backups: [
      {
        id: "backup-1",
        status: "FAILED",
        created_at: "2026-08-11T15:00:00Z",
      } as BackupManifest,
    ],
    updateStatus: {
      state: "ERROR",
      current_version: "0.24.0-alpha.1",
      message: "Private update diagnostic",
      checked_at: "2026-08-11T16:00:00Z",
    },
  };
}

describe("desktop notification collection", () => {
  afterEach(() => vi.restoreAllMocks());

  it("creates bounded action notifications without leaking source details", () => {
    const notifications = collectDesktopNotifications(sourceSnapshot());

    expect(notifications.map(({ kind }) => kind)).toEqual([
      "UPDATE_FAILED",
      "BACKUP_FAILED",
      "FOLLOW_UP_DUE",
      "OFFER_RECEIVED",
      "MFA_REQUIRED",
    ]);
    const rendered = JSON.stringify(notifications);
    expect(rendered).not.toContain("Secret Employer");
    expect(rendered).not.toContain("Secret offer subject");
    expect(rendered).not.toContain("Private message body");
    expect(rendered).not.toContain("Private update diagnostic");
  });

  it("uses challenge detail for CAPTCHA and approaching assessment deadlines", () => {
    const snapshot = sourceSnapshot();
    snapshot.workflows[0] = {
      ...snapshot.workflows[0]!,
      state: "CAPTCHA_REQUIRED",
    };
    snapshot.challenges = [
      {
        id: "challenge-captcha",
        workflow_id: "workflow-1",
        detection: { kind: "CAPTCHA" },
        status: "INTERVENTION_REQUIRED",
        remaining_seconds: null,
        updated_at: "2026-08-11T17:00:00Z",
      } as ChallengeSessionSnapshot,
      {
        id: "challenge-assessment",
        workflow_id: "workflow-2",
        detection: { kind: "ASSESSMENT" },
        status: "IN_PROGRESS",
        remaining_seconds: 600,
        updated_at: "2026-08-11T18:00:00Z",
      } as ChallengeSessionSnapshot,
    ];

    const notifications = collectDesktopNotifications(snapshot);

    expect(
      notifications.filter(({ kind }) => kind === "CAPTCHA_REQUIRED"),
    ).toHaveLength(1);
    expect(
      notifications.some(
        ({ title }) => title === "Assessment deadline is approaching",
      ),
    ).toBe(true);
  });

  it("creates privacy-safe reminders from locally synced interview events", () => {
    const snapshot = sourceSnapshot();
    snapshot.calendarEvents = [
      {
        provider: "GOOGLE_CALENDAR",
        event: {
          provider_event_id: "private-provider-event-id",
          title: "Technical interview with Secret Employer",
          start_at: "2026-08-11T16:45:00Z",
          end_at: "2026-08-11T17:45:00Z",
          time_zone: "UTC",
          attendees: ["private@example.invalid"],
          conferencing_url: "https://meet.example.invalid/private",
          location: "Private room",
        },
        synced_at: "2026-08-11T16:00:00Z",
      } satisfies SyncedCalendarEvent,
    ];

    const notifications = collectDesktopNotifications(
      snapshot,
      new Date("2026-08-11T16:15:00Z"),
    );
    const reminder = notifications.find(
      ({ kind }) => kind === "INTERVIEW_REMINDER",
    );
    expect(reminder?.title).toBe("Interview starts within one hour");
    const rendered = JSON.stringify(reminder);
    expect(rendered).not.toContain("Secret Employer");
    expect(rendered).not.toContain("private-provider-event-id");
    expect(rendered).not.toContain("private@example.invalid");
    expect(rendered).not.toContain("meet.example.invalid");
  });

  it("delivers each native notification once and persists the opt-in", async () => {
    let persisted: NotificationPersistentState = {
      native_enabled: false,
      delivered_ids: [],
    };
    const shown: DesktopNotificationItem[] = [];
    const activated: DesktopNotificationItem[] = [];
    const manager = new DesktopNotificationManager(
      async () => sourceSnapshot(),
      {
        load: async () => persisted,
        save: async (state) => {
          persisted = state;
        },
      },
      {
        isSupported: () => true,
        show: (notification, onActivate) => {
          shown.push(notification);
          onActivate();
        },
      },
      (notification) => activated.push(notification),
    );

    await manager.initialize();
    await manager.setNativeEnabled(true);
    await manager.refresh();
    manager.stop();

    expect(shown).toHaveLength(5);
    expect(activated).toEqual(shown);
    expect(persisted.native_enabled).toBe(true);
    expect(persisted.delivered_ids).toHaveLength(5);
    expect(manager.status.active_notifications).toHaveLength(5);
    expect(manager.status.last_error).toBeNull();
  });

  it("coalesces concurrent refreshes before native delivery", async () => {
    let releaseSnapshot: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      releaseSnapshot = resolve;
    });
    const loadSnapshot = vi.fn(async () => {
      await gate;
      return sourceSnapshot();
    });
    const shown: DesktopNotificationItem[] = [];
    const manager = new DesktopNotificationManager(
      loadSnapshot,
      {
        load: async () => ({ native_enabled: true, delivered_ids: [] }),
        save: async () => undefined,
      },
      {
        isSupported: () => true,
        show: (notification) => shown.push(notification),
      },
      () => undefined,
    );
    await manager.initialize();

    const first = manager.refresh();
    const second = manager.refresh();
    releaseSnapshot?.();
    await Promise.all([first, second]);
    manager.stop();

    expect(first).toBe(second);
    expect(loadSnapshot).toHaveBeenCalledOnce();
    expect(shown).toHaveLength(5);
  });
});
