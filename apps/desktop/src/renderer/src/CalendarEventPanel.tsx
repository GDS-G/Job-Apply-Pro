import { useEffect, useMemo, useRef, useState } from "react";

import type {
  CalendarMutationCreate,
  CalendarMutationPlan,
  CommunicationMutationAudit,
  IntegrationHealth,
  ProviderConfigurationStatus,
  WorkflowRunSnapshot,
} from "@job-apply-pro/contracts";

type CalendarProvider = "GOOGLE_CALENDAR" | "OUTLOOK_CALENDAR";

const writeScopes: Record<CalendarProvider, string> = {
  GOOGLE_CALENDAR: "https://www.googleapis.com/auth/calendar.events",
  OUTLOOK_CALENDAR: "Calendars.ReadWrite",
};

function supportedMailbox(value: unknown): boolean {
  if (typeof value !== "string" || value.length > 254) return false;
  const match =
    /^([A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*)@([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)$/.exec(
      value,
    );
  return (
    !!match &&
    match[1]!.length <= 64 &&
    match[2]!.length <= 253 &&
    match[2]!
      .split(".")
      .every(
        (part) =>
          part.length >= 1 &&
          part.length <= 63 &&
          !part.startsWith("-") &&
          !part.endsWith("-"),
      )
  );
}

export function eligibleCalendarWriteProviders(
  integrations: IntegrationHealth[],
  configuration: ProviderConfigurationStatus | null,
): IntegrationHealth[] {
  if (
    !configuration ||
    (configuration.source !== "ENVIRONMENT" &&
      configuration.source !== "ENCRYPTED_DATABASE")
  ) {
    return [];
  }
  return integrations.filter((integration) => {
    if (
      integration.provider !== "GOOGLE_CALENDAR" &&
      integration.provider !== "OUTLOOK_CALENDAR"
    ) {
      return false;
    }
    const provider = integration.provider;
    const registrations = configuration.providers.filter(
      (item) => item.provider === provider,
    );
    const registration = registrations[0];
    const scope = writeScopes[provider];
    return (
      registrations.length === 1 &&
      integrations.filter((item) => item.provider === provider).length === 1 &&
      registration?.oauth_configured === true &&
      registration.write_enabled &&
      registration.requested_scopes.includes(scope) &&
      integration.status === "CONNECTED" &&
      integration.write_enabled &&
      integration.granted_scopes.includes(scope) &&
      supportedMailbox(integration.account_hint)
    );
  });
}

function localDateTime(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
  const result = new Date(value);
  if (!Number.isFinite(result.getTime())) return null;
  const expected = value.split(/[-T:]/).map(Number);
  if (
    result.getFullYear() !== expected[0] ||
    result.getMonth() + 1 !== expected[1] ||
    result.getDate() !== expected[2] ||
    result.getHours() !== expected[3] ||
    result.getMinutes() !== expected[4]
  ) {
    return null;
  }
  return result;
}

function currentTimeZone(): string {
  const value = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return value || "UTC";
}

function localIsoWithOffset(value: string, parsed: Date): string {
  const offsetMinutes = -parsed.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absolute = Math.abs(offsetMinutes);
  const hours = Math.floor(absolute / 60)
    .toString()
    .padStart(2, "0");
  const minutes = (absolute % 60).toString().padStart(2, "0");
  return `${value}:00${sign}${hours}:${minutes}`;
}

function calendarOutcome(audit: CommunicationMutationAudit): string {
  switch (audit.status) {
    case "CONFIRMED":
      return "The provider accepted this creation and returned an event ID. This is not an exact event read-back or proof of invitation delivery. No attendees or invitations were requested. Do not retry this plan.";
    case "UNCERTAIN":
      return "Calendar creation outcome is uncertain. Inspect the bound provider calendar; do not retry this plan or create a duplicate event.";
    case "PLANNED":
      return "The calendar attempt was admitted but its final outcome is unknown. Inspect the bound provider calendar; do not retry this plan.";
    case "FAILED":
      return "The provider reported that this admitted attempt was not applied. The plan is permanently closed; inspect the provider calendar before preparing a separate event.";
    case "ACCEPTED":
      return "The calendar service returned an unsupported result. Inspect the bound provider calendar; do not retry this plan.";
  }
}

function eligibilitySignature(providers: IntegrationHealth[]): string {
  return JSON.stringify(
    providers.map((provider) => ({
      provider: provider.provider,
      account_hint: provider.account_hint,
      granted_scopes: [...provider.granted_scopes].sort(),
    })),
  );
}

export function CalendarEventPanel({
  backendReady,
  providers,
  workflows,
}: {
  backendReady: boolean;
  providers: IntegrationHealth[];
  workflows: WorkflowRunSnapshot[];
}) {
  const available = providers.filter(
    (item): item is IntegrationHealth & { provider: CalendarProvider } =>
      item.provider === "GOOGLE_CALENDAR" ||
      item.provider === "OUTLOOK_CALENDAR",
  );
  const [provider, setProvider] = useState<CalendarProvider>(
    available[0]?.provider ?? "GOOGLE_CALENDAR",
  );
  const [workflowId, setWorkflowId] = useState("");
  const [title, setTitle] = useState("");
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");
  const [location, setLocation] = useState("");
  const [plan, setPlan] = useState<CalendarMutationPlan | null>(null);
  const [audit, setAudit] = useState<CommunicationMutationAudit | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const active = useRef(false);
  const attemptSubmitted = useRef(false);
  const generation = useRef(0);
  const timeZone = useMemo(currentTimeZone, []);
  const eligibility = eligibilitySignature(available);
  const previousEligibility = useRef(eligibility);

  useEffect(() => {
    if (previousEligibility.current === eligibility) return;
    previousEligibility.current = eligibility;
    generation.current += 1;
    active.current = false;
    setBusy(false);
    if (attemptSubmitted.current) {
      setAudit(null);
      setBlocked(true);
      setNotice(null);
      setError(
        "Calendar account or write capability changed during native review. Its outcome may be unresolved; inspect the bound provider calendar and do not retry this plan.",
      );
      return;
    }
    setPlan(null);
    setAudit(null);
    setBlocked(false);
    setProvider(available[0]?.provider ?? "GOOGLE_CALENDAR");
    setError(null);
    setNotice(
      "Calendar account or write capability changed. Prepare a fresh exact plan before requesting provider creation.",
    );
  }, [available, eligibility]);

  const start = localDateTime(startAt);
  const end = localDateTime(endAt);
  const workflowValid =
    !workflowId || workflows.some((item) => item.workflow_id === workflowId);
  const canPrepare =
    backendReady &&
    available.some((item) => item.provider === provider) &&
    !busy &&
    !plan &&
    !blocked &&
    !!title.trim() &&
    !!start &&
    !!end &&
    end.getTime() > start.getTime() &&
    workflowValid;
  const canCreate = backendReady && !!plan && !busy && !blocked && !audit;

  async function preparePlan() {
    if (!canPrepare || !start || !end || active.current) return;
    active.current = true;
    const request = ++generation.current;
    setBusy(true);
    setError(null);
    setNotice(null);
    const input: CalendarMutationCreate = {
      provider,
      workflow_id: workflowId || null,
      event: {
        title,
        start_at: localIsoWithOffset(startAt, start),
        end_at: localIsoWithOffset(endAt, end),
        time_zone: timeZone,
        attendees: [],
        conferencing_url: null,
        location: location.trim() ? location : null,
        attendee_notification_policy: "NONE",
        reminder_policy: "NONE",
        visibility_policy: "PRIVATE",
        availability_policy: "BUSY",
      },
    };
    try {
      const created =
        await window.jobApplyPro.workbench.createCalendarPlan(input);
      if (request !== generation.current) return;
      setPlan(created);
      setNotice(
        "Exact event plan saved for review. Nothing was sent to the provider. The event is fixed to private, busy, no reminders, no attendees, no invitations, and no conferencing.",
      );
    } catch {
      if (request === generation.current) {
        setError(
          "Calendar review could not be prepared. Refresh the connected account and verify the event fields. No provider event request was made.",
        );
      }
    } finally {
      if (request === generation.current) {
        active.current = false;
        setBusy(false);
      }
    }
  }

  async function createEvent() {
    if (!canCreate || !plan || active.current) return;
    active.current = true;
    const request = ++generation.current;
    setBusy(true);
    attemptSubmitted.current = true;
    setBlocked(true);
    setError(null);
    setNotice(null);
    try {
      const result =
        await window.jobApplyPro.workbench.reviewAndCreateCalendarEvent(
          plan.id,
          plan.fingerprint,
        );
      if (request !== generation.current) return;
      if (result === null) {
        attemptSubmitted.current = false;
        active.current = false;
        setBlocked(false);
        setNotice(
          "Native approval cancelled. No provider event request was made.",
        );
      } else if ("outcome" in result) {
        if (
          result.outcome !== "NOT_DISPATCHED" ||
          result.reason !== "REVIEW_UNAVAILABLE"
        ) {
          throw new Error("Calendar review result is invalid.");
        }
        attemptSubmitted.current = false;
        active.current = false;
        setBlocked(false);
        setPlan(null);
        setNotice(
          "No provider event request was dispatched by this review. The plan or account may be stale; refresh connections and prepare a fresh exact plan.",
        );
      } else {
        setAudit(result);
        setBlocked(true);
        setNotice(calendarOutcome(result));
      }
    } catch {
      if (request !== generation.current) return;
      setBlocked(true);
      setError(
        "Calendar creation result could not be confirmed. Inspect the bound provider calendar; do not retry this plan or create a duplicate event.",
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
      className="calendar-event-panel"
      aria-labelledby="calendar-event-title"
      aria-busy={busy}
    >
      <div className="panel__header panel__header--subsection">
        <div>
          <h3 id="calendar-event-title">Reviewed calendar event creation</h3>
          <p>
            Create-only and one admitted provider attempt per exact plan. This
            release creates a private, busy event with reminders disabled; it
            does not add attendees, send invitations, create conferencing, or
            update existing events.
          </p>
        </div>
      </div>
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
          void preparePlan();
        }}
      >
        <label>
          Bound calendar provider
          <select
            value={provider}
            disabled={busy || !!plan || blocked}
            onChange={(event) =>
              setProvider(event.target.value as CalendarProvider)
            }
          >
            {available.map((item) => (
              <option key={item.provider} value={item.provider}>
                {item.provider.replaceAll("_", " ")} · {item.account_hint}
              </option>
            ))}
          </select>
        </label>
        <label>
          Owning workflow (optional)
          <select
            value={workflowId}
            disabled={busy || !!plan || blocked}
            onChange={(event) => setWorkflowId(event.target.value)}
          >
            <option value="">No workflow</option>
            {workflows.map((workflow) => (
              <option key={workflow.workflow_id} value={workflow.workflow_id}>
                {workflow.employer} · {workflow.title} · {workflow.workflow_id}
              </option>
            ))}
          </select>
        </label>
        <label className="calendar-event-panel__wide">
          Event title
          <input
            required
            maxLength={1000}
            value={title}
            disabled={busy || !!plan || blocked}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label>
          Starts
          <input
            type="datetime-local"
            required
            value={startAt}
            disabled={busy || !!plan || blocked}
            onChange={(event) => setStartAt(event.target.value)}
          />
        </label>
        <label>
          Ends
          <input
            type="datetime-local"
            required
            value={endAt}
            disabled={busy || !!plan || blocked}
            onChange={(event) => setEndAt(event.target.value)}
          />
        </label>
        <label>
          Time zone
          <input readOnly value={timeZone} />
        </label>
        <label>
          Location (optional)
          <input
            maxLength={1000}
            value={location}
            disabled={busy || !!plan || blocked}
            onChange={(event) => setLocation(event.target.value)}
          />
        </label>
        <p className="calendar-event-panel__wide">
          Fixed event policy: visibility is private, availability is busy,
          provider-default reminders are disabled, attendees are fixed to none,
          invitation delivery is disabled, and no conferencing link is
          requested. The native dialog will show the exact bound account,
          primary calendar, title, times, time zone, location, fixed policies,
          and review fingerprint before the attempt.
        </p>
        <button
          className="button button--secondary"
          type="submit"
          disabled={!canPrepare}
        >
          Prepare exact event review
        </button>
      </form>
      {plan && (
        <article className="calendar-event-review">
          <h4>Exact saved calendar plan</h4>
          <dl>
            <div>
              <dt>Provider account</dt>
              <dd>
                {plan.provider.replaceAll("_", " ")} · {plan.account_label}
              </dd>
            </div>
            <div>
              <dt>Calendar target</dt>
              <dd>{plan.calendar_target}</dd>
            </div>
            <div>
              <dt>Title</dt>
              <dd>{plan.event.title}</dd>
            </div>
            <div>
              <dt>Time</dt>
              <dd>
                {plan.event.start_at} — {plan.event.end_at}
              </dd>
            </div>
            <div>
              <dt>Time zone</dt>
              <dd>{plan.event.time_zone}</dd>
            </div>
            <div>
              <dt>Location</dt>
              <dd>{plan.event.location || "None"}</dd>
            </div>
            <div>
              <dt>Invitations</dt>
              <dd>None — no attendees</dd>
            </div>
            <div>
              <dt>Reminders</dt>
              <dd>None — provider defaults disabled</dd>
            </div>
            <div>
              <dt>Visibility</dt>
              <dd>PRIVATE</dd>
            </div>
            <div>
              <dt>Availability</dt>
              <dd>BUSY</dd>
            </div>
            <div>
              <dt>Review SHA-256</dt>
              <dd>
                <code>{plan.fingerprint}</code>
              </dd>
            </div>
          </dl>
          {audit ? (
            <p role="status">
              Attempt {audit.status.replaceAll("_", " ")}
              {audit.provider_resource_id
                ? ` · provider event ${audit.provider_resource_id}`
                : ""}
            </p>
          ) : null}
          {!blocked ? (
            <div className="calendar-event-review__actions">
              <button
                className="button button--primary"
                type="button"
                disabled={!canCreate}
                onClick={() => void createEvent()}
              >
                Review &amp; create with native approval
              </button>
              <button
                className="button button--secondary"
                type="button"
                disabled={busy}
                onClick={() => {
                  attemptSubmitted.current = false;
                  setPlan(null);
                  setNotice(
                    "Prepared plan removed from this view. No provider event request was made.",
                  );
                }}
              >
                Discard unattempted review
              </button>
            </div>
          ) : null}
        </article>
      )}
    </section>
  );
}
