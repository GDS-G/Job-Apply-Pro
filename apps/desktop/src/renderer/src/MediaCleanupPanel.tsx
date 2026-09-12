import { useCallback, useEffect, useRef, useState } from "react";

import type { MediaCleanupPublicRecord } from "@job-apply-pro/contracts";

const confirmationPhrase = "I VERIFIED PROVIDER MEDIA CLEANUP";

function displayTime(value: string | null): string {
  if (!value) return "Not scheduled";
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? date.toLocaleString()
    : "Unavailable";
}

function providerLabel(providerId: string): string {
  switch (providerId) {
    case "gemini":
      return "Gemini";
    case "openai":
      return "OpenAI";
    case "anthropic":
      return "Anthropic";
    default:
      return "Configured provider";
  }
}

function recoveryDescription(item: MediaCleanupPublicRecord): string {
  if (item.state === "MANUAL_REVIEW") {
    if (!item.known_resource) {
      return "The provider resource is unknown. Automatic deletion is unavailable; inspect the original provider account and verify cleanup yourself.";
    }
    return "Encrypted recovery metadata requires operator repair or restore support. This record is retained and cannot be acknowledged as unknown-resource cleanup.";
  }
  if (item.state === "DELETE_PENDING") {
    return "Automatic deletion is pending. A retry uses the retained resource only; it does not upload media or run a model.";
  }
  return "Media is uploading or in use. Recovery respects the active lease before attempting deletion.";
}

function recoveryReason(reason: string | null): string | null {
  switch (reason) {
    case "DELETE_FAILED":
      return "The previous deletion was not confirmed; cleanup remains pending.";
    case "UNREADABLE_RESOURCE":
      return "Encrypted resource metadata could not be read; operator review is required.";
    default:
      return null;
  }
}

type RecoveryAction = "refresh" | "retry" | "resolve";

export function MediaCleanupPanel({ backendReady }: { backendReady: boolean }) {
  const [items, setItems] = useState<MediaCleanupPublicRecord[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const requestGeneration = useRef(0);
  const requestActive = useRef(false);

  const perform = useCallback(
    async (
      action: RecoveryAction,
      item?: MediaCleanupPublicRecord,
      phrase?: string,
    ) => {
      if (!backendReady || requestActive.current) return;
      if (
        action === "resolve" &&
        (item?.state !== "MANUAL_REVIEW" ||
          item.known_resource ||
          phrase !== confirmationPhrase)
      )
        return;
      requestActive.current = true;
      const generation = ++requestGeneration.current;
      setBusy(true);
      setError(null);
      setNotice(null);
      setSelectedId(null);
      setConfirmation("");
      try {
        const api = window.jobApplyPro.workbench;
        const response =
          action === "refresh"
            ? await api.listMediaCleanup()
            : action === "retry"
              ? await api.retryMediaCleanup()
              : await api.resolveMediaCleanup(
                  item!.id,
                  item!.updated_at,
                  phrase!,
                );
        if (generation !== requestGeneration.current) return;
        setItems(response.items.filter((record) => record.state !== "DELETED"));
        setLoaded(true);
        setNotice(
          action === "resolve"
            ? "Operator acknowledgement recorded. This does not independently confirm remote deletion."
            : action === "retry"
              ? "Deletion-only recovery pass finished. Remaining records are shown below. No media was uploaded."
              : null,
        );
      } catch {
        if (generation !== requestGeneration.current) return;
        // Provider and IPC error strings can contain private context. Never render them.
        setLoaded(false);
        setError(
          action === "resolve"
            ? "Acknowledgement was not confirmed. The record may have changed. Refresh and review the latest state before trying again."
            : "Media cleanup status could not be confirmed. Refresh before taking another recovery action.",
        );
      } finally {
        if (generation === requestGeneration.current) {
          requestActive.current = false;
          setBusy(false);
        }
      }
    },
    [backendReady],
  );

  useEffect(() => {
    setLoaded(false);
    setItems([]);
    setSelectedId(null);
    setConfirmation("");
    setNotice(null);
    setError(null);
    setBusy(false);
    requestActive.current = false;
    if (backendReady) void perform("refresh");
    return () => {
      requestGeneration.current += 1;
    };
  }, [backendReady, perform]);

  const actionsDisabled = !backendReady || busy || !loaded;
  const automaticItems = items.filter((item) => item.state !== "MANUAL_REVIEW");
  const manualItems = items.filter((item) => item.state === "MANUAL_REVIEW");

  return (
    <section aria-labelledby="media-cleanup-title" aria-busy={busy}>
      <div className="panel__header panel__header--subsection">
        <div>
          <h3 id="media-cleanup-title">Durable media recovery</h3>
          <p>
            Unresolved provider-media cleanup only. Resource names, URLs, and
            credentials are not displayed.
          </p>
        </div>
        <div className="button-row">
          <button
            className="button button--secondary"
            type="button"
            disabled={!backendReady || busy}
            onClick={() => void perform("refresh")}
          >
            Refresh media cleanup
          </button>
          <button
            className="button button--secondary"
            type="button"
            disabled={actionsDisabled || automaticItems.length === 0}
            onClick={() => void perform("retry")}
          >
            Retry automatic deletion
          </button>
        </div>
      </div>
      {!backendReady && (
        <p role="status" className="empty-state empty-state--compact">
          Connect the local backend to inspect media cleanup.
        </p>
      )}
      {busy && (
        <p role="status" className="empty-state empty-state--compact">
          Checking media recovery…
        </p>
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
      {loaded && items.length === 0 && (
        <p className="empty-state empty-state--compact">
          No unresolved media cleanup records.
        </p>
      )}
      {items.length > 0 && (
        <div className="operations-reports">
          {[
            {
              title: "Automatic cleanup / active leases",
              records: automaticItems,
            },
            { title: "Manual review required", records: manualItems },
          ].map((group) => (
            <article key={group.title}>
              <h4>
                {group.title} ({group.records.length})
              </h4>
              {group.records === automaticItems && (
                <p>
                  Automatic deletion requires the original provider credentials.
                  A different configured account will not be used for deletion.
                </p>
              )}
              <div className="operations-report-list">
                {group.records.map((item) => (
                  <div key={`${item.id}:${item.updated_at}`}>
                    <strong>
                      {providerLabel(item.provider_id)} ·{" "}
                      {item.state === "MANUAL_REVIEW"
                        ? item.known_resource
                          ? "Provider review required"
                          : "Unknown resource — manual review"
                        : item.state === "DELETE_PENDING"
                          ? "Deletion pending"
                          : "Active lease / awaiting recovery"}
                    </strong>
                    <span>{recoveryDescription(item)}</span>
                    {recoveryReason(item.reason) && (
                      <span>{recoveryReason(item.reason)}</span>
                    )}
                    <small>Cleanup record: {item.id}</small>
                    <small>
                      Deletion attempts: {item.attempts} · Updated:{" "}
                      {displayTime(item.updated_at)}
                    </small>
                    {item.lease_until && (
                      <small>
                        Lease until: {displayTime(item.lease_until)}
                      </small>
                    )}
                    {item.next_attempt_at && (
                      <small>
                        Next eligible retry: {displayTime(item.next_attempt_at)}
                      </small>
                    )}
                    {item.state === "MANUAL_REVIEW" &&
                      !item.known_resource &&
                      (selectedId === item.id ? (
                        <form
                          className="workbench-form"
                          onSubmit={(event) => {
                            event.preventDefault();
                            if (!actionsDisabled)
                              void perform("resolve", item, confirmation);
                          }}
                        >
                          <p>
                            Acknowledge only after checking the original
                            provider account. This records your verification;
                            the app does not verify remote deletion.
                          </p>
                          <label>
                            Type {confirmationPhrase}
                            <input
                              value={confirmation}
                              autoComplete="off"
                              spellCheck={false}
                              maxLength={confirmationPhrase.length + 1}
                              disabled={actionsDisabled}
                              onChange={(event) =>
                                setConfirmation(event.target.value)
                              }
                            />
                          </label>
                          <div className="button-row">
                            <button
                              className="button button--secondary"
                              type="submit"
                              disabled={
                                actionsDisabled ||
                                confirmation !== confirmationPhrase
                              }
                            >
                              Record operator acknowledgement
                            </button>
                            <button
                              className="button button--ghost"
                              type="button"
                              disabled={busy}
                              onClick={() => {
                                setSelectedId(null);
                                setConfirmation("");
                              }}
                            >
                              Cancel
                            </button>
                          </div>
                        </form>
                      ) : (
                        <button
                          className="button button--secondary"
                          type="button"
                          disabled={actionsDisabled}
                          onClick={() => {
                            setSelectedId(item.id);
                            setConfirmation("");
                          }}
                        >
                          Review manual cleanup
                        </button>
                      ))}
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
