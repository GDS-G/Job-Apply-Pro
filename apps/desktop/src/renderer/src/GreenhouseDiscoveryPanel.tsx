import { useEffect, useRef, useState } from "react";

import type {
  GreenhouseJobList,
  GreenhouseJobReview,
  WorkflowRunSnapshot,
} from "@job-apply-pro/contracts";

type Pending = "list" | "review" | "import" | null;

export function GreenhouseDiscoveryPanel({
  backendReady,
  profileId,
  onImported,
}: {
  backendReady: boolean;
  profileId: string | null;
  onImported: (workflow: WorkflowRunSnapshot) => void | Promise<void>;
}) {
  const [boardToken, setBoardToken] = useState("");
  const [listing, setListing] = useState<GreenhouseJobList | null>(null);
  const [postingId, setPostingId] = useState("");
  const [review, setReview] = useState<{
    job: GreenhouseJobReview;
    profileId: string | null;
  } | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [importFinished, setImportFinished] = useState(false);
  const [changedSources, setChangedSources] = useState<Set<string>>(new Set());
  const generation = useRef(0);
  const active = useRef(false);

  function invalidateReview() {
    generation.current += 1;
    active.current = false;
    setPending(null);
    setReview(null);
    setImportFinished(false);
    setNotice(null);
    setError(null);
  }

  useEffect(() => {
    generation.current += 1;
    active.current = false;
    setPending(null);
    setReview(null);
    setImportFinished(false);
    setNotice(null);
    setError(null);
    if (!backendReady) {
      setListing(null);
      setPostingId("");
    }
    return () => {
      generation.current += 1;
    };
  }, [backendReady, profileId]);

  const tokenValid =
    /^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/.test(boardToken) &&
    boardToken.toLowerCase() !== "internal";
  const selected = listing?.jobs.find((job) => job.posting_id === postingId);
  const sourceChanged =
    !!review &&
    changedSources.has(`${review.job.board_token}:${review.job.posting_id}`);
  const canReview = backendReady && !!selected && !pending;
  const canImport =
    backendReady &&
    !!profileId &&
    !!review &&
    review.profileId === profileId &&
    review.job.board_token === listing?.board_token &&
    review.job.posting_id === postingId &&
    !sourceChanged &&
    !pending &&
    !importFinished;

  function begin(operation: Exclude<Pending, null>): number {
    active.current = true;
    setPending(operation);
    setError(null);
    setNotice(null);
    return ++generation.current;
  }

  function finish(request: number) {
    if (request !== generation.current) return;
    active.current = false;
    setPending(null);
  }

  async function listJobs() {
    if (!backendReady || !tokenValid || active.current) return;
    const request = begin("list");
    setListing(null);
    setPostingId("");
    setReview(null);
    setImportFinished(false);
    try {
      const result = await window.jobApplyPro.workbench.listGreenhouseJobs({
        board_token: boardToken,
      });
      if (request !== generation.current) return;
      if (result.board_token !== boardToken)
        throw new Error("The listing did not match the requested board.");
      setListing(result);
    } catch {
      if (request === generation.current)
        setError(
          "Public jobs could not be loaded. Check the board token and try again.",
        );
    } finally {
      finish(request);
    }
  }

  async function reviewJob() {
    if (!canReview || !listing || !selected || active.current) return;
    const request = begin("review");
    setReview(null);
    setImportFinished(false);
    try {
      const result = await window.jobApplyPro.workbench.reviewGreenhouseJob({
        board_token: listing.board_token,
        posting_id: selected.posting_id,
      });
      if (request !== generation.current) return;
      if (
        result.board_token !== listing.board_token ||
        result.posting_id !== selected.posting_id
      ) {
        throw new Error("The job review did not match the selection.");
      }
      setReview({ job: result, profileId });
    } catch {
      if (request === generation.current)
        setError(
          "This job could not be reviewed. Refresh the public listings and select it again.",
        );
    } finally {
      finish(request);
    }
  }

  async function importJob() {
    if (!canImport || !review || !profileId || active.current) return;
    const request = begin("import");
    try {
      const result = await window.jobApplyPro.workbench.importGreenhouseJob({
        board_token: review.job.board_token,
        posting_id: review.job.posting_id,
        review_fingerprint: review.job.review_fingerprint,
        profile_id: profileId,
      });
      if (request !== generation.current) return;
      switch (result.outcome) {
        case "IMPORTED":
        case "EXISTING": {
          if (
            !result.job ||
            !result.workflow ||
            result.workflow.profile_id !== profileId
          )
            throw new Error("The local import result could not be verified.");
          setImportFinished(true);
          setNotice(
            result.outcome === "IMPORTED"
              ? "Job imported into your local workflow queue. Qualification is not evaluated. No application was submitted."
              : "This exact job already has a local workflow for this profile. The existing workflow was reused; no application was submitted.",
          );
          try {
            await onImported(result.workflow);
          } catch {
            if (request === generation.current)
              setError(
                "The job is saved locally, but the workflow queue could not be refreshed. Refresh the queue before continuing.",
              );
          }
          break;
        }
        case "STALE_REVIEW":
          setReview(null);
          setNotice(
            "The posting changed since this review. Review the current job again before importing.",
          );
          break;
        case "SOURCE_CHANGED":
          setImportFinished(true);
          setChangedSources(
            (current) =>
              new Set([
                ...current,
                `${review.job.board_token}:${review.job.posting_id}`,
              ]),
          );
          setNotice(
            "The previously imported job has changed at its source. Updating an imported snapshot is not supported; another review will not replace it.",
          );
          break;
        case "SOURCE_UNAVAILABLE":
          setReview(null);
          setNotice(
            "The source job is unavailable. Refresh the public listings before selecting a job again.",
          );
          setListing(null);
          setPostingId("");
          break;
        default:
          throw new Error("The local import result is invalid.");
      }
    } catch {
      if (request === generation.current) {
        setImportFinished(true);
        setError(
          "The local import result could not be confirmed. No application submission was requested. Refresh the workflow queue before reviewing again.",
        );
      }
    } finally {
      finish(request);
    }
  }

  return (
    <section
      className="panel greenhouse-discovery-panel"
      aria-labelledby="greenhouse-discovery-title"
      aria-busy={!!pending}
    >
      <div className="panel__header">
        <div>
          <h2 id="greenhouse-discovery-title">
            Greenhouse public job discovery
          </h2>
          <p>
            Read public listings, review one job, then save it locally. No
            candidate information is sent to the job board and no application is
            submitted.
          </p>
        </div>
        <span className="status-pill">Public read-only source</span>
      </div>
      {!backendReady && (
        <p role="status">Connect the local backend to discover public jobs.</p>
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
          void listJobs();
        }}
      >
        <label>
          Greenhouse board token
          <input
            value={boardToken}
            maxLength={100}
            spellCheck={false}
            autoComplete="off"
            disabled={!backendReady || pending === "import"}
            onChange={(event) => {
              invalidateReview();
              setBoardToken(event.target.value);
              setListing(null);
              setPostingId("");
            }}
            aria-describedby="greenhouse-board-help"
          />
        </label>
        <p id="greenhouse-board-help">
          Enter the public board token, not a URL or API key. Requests run only
          when you choose an action.
        </p>
        <button
          className="button button--secondary"
          type="submit"
          disabled={!backendReady || !tokenValid || !!pending}
        >
          Preview public jobs
        </button>
      </form>
      {listing && (
        <div className="greenhouse-discovery-results">
          <h3>{listing.board_name}</h3>
          <p>
            Board: {listing.board_token} · Fetched: {listing.fetched_at}
          </p>
          <p>
            {listing.jobs.length} public job listings ·{" "}
            {listing.excluded_prospect_count} prospect postings excluded
          </p>
          {listing.jobs.length ? (
            <>
              <label>
                Public job to review
                <select
                  value={postingId}
                  disabled={pending === "import" || !backendReady}
                  onChange={(event) => {
                    invalidateReview();
                    setPostingId(event.target.value);
                  }}
                >
                  <option value="">Choose one job</option>
                  {listing.jobs.map((job) => (
                    <option key={job.posting_id} value={job.posting_id}>
                      {job.title} · {job.location ?? "Location not provided"} ·{" "}
                      {job.posting_id}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="button button--secondary"
                type="button"
                disabled={!canReview}
                onClick={() => void reviewJob()}
              >
                Review selected job
              </button>
            </>
          ) : (
            <p>No public job listings were returned for this board.</p>
          )}
        </div>
      )}
      {review && (
        <article className="greenhouse-job-review">
          <h3>{review.job.title}</h3>
          <p>
            {review.job.employer} ·{" "}
            {review.job.location ?? "Location not provided"}
          </p>
          <p>
            Posting: {review.job.posting_id} · Board: {review.job.board_token}
          </p>
          <p>
            Qualification: not evaluated. Importing does not establish
            eligibility.
          </p>
          <p>Public API source: {review.job.api_url}</p>
          <p>Reported posting URL: {review.job.reported_url}</p>
          {review.job.source_url && (
            <p>Recognized source URL: {review.job.source_url}</p>
          )}
          <p>
            {review.job.navigation_supported
              ? "A supported source URL was recognized. No browser will be opened by this panel."
              : "Custom or unsupported destination: displayed as text only. Navigation is not enabled."}
          </p>
          <p>
            Provider updated: {review.job.provider_updated_at ?? "Not reported"}{" "}
            · Reviewed: {review.job.fetched_at}
          </p>
          <p>Normalizer: {review.job.normalizer_version}</p>
          <pre>{review.job.description}</pre>
          <p>
            Review fingerprint: <code>{review.job.review_fingerprint}</code>
          </p>
          {sourceChanged && (
            <p className="warning-banner">
              This imported source has changed. Updating its saved snapshot is
              unsupported; reviewing again does not enable replacement.
            </p>
          )}
          <p>
            {profileId
              ? `Import for candidate profile: ${profileId}`
              : "Select or create a candidate profile, then review this job again before importing."}
          </p>
          <button
            className="button button--primary"
            type="button"
            disabled={!canImport}
            onClick={() => void importJob()}
          >
            Import reviewed job locally
          </button>
        </article>
      )}
    </section>
  );
}
