import { useEffect, useRef, useState } from "react";
import type {
  DocumentSelectionRequest,
  FindingStatus,
  GreenhouseApplicationLaunchPreview,
  JobReadinessSnapshot,
  QualificationPreview,
  QualificationRequest,
  ReadinessSelectionPreview,
  RequirementClassification,
  RequirementFinding,
  RequirementsPreview,
  RequirementsRequest,
  SupervisedPortalRunSnapshot,
} from "@job-apply-pro/contracts";

type Pending =
  | "load"
  | "requirements"
  | "qualification"
  | "resume"
  | "approval"
  | "launch-preview"
  | "launch";

export function JobReadinessPanel({
  backendReady,
  applicationId,
  profileId,
  onChanged,
  onPortalStarted,
}: {
  backendReady: boolean;
  applicationId: string | null;
  profileId: string | null;
  onChanged: () => void | Promise<void>;
  onPortalStarted?: (run: SupervisedPortalRunSnapshot) => void | Promise<void>;
}) {
  const [snapshot, setSnapshot] = useState<JobReadinessSnapshot | null>(null);
  const [choices, setChoices] = useState<
    Record<string, RequirementClassification | "">
  >({});
  const [findings, setFindings] = useState<RequirementFinding[]>([]);
  const [requirementsPreview, setRequirementsPreview] = useState<{
    input: RequirementsRequest;
    result: RequirementsPreview;
  } | null>(null);
  const [qualificationPreview, setQualificationPreview] = useState<{
    input: QualificationRequest;
    result: QualificationPreview;
  } | null>(null);
  const [resumePreview, setResumePreview] = useState<{
    input: DocumentSelectionRequest;
    result: ReadinessSelectionPreview;
  } | null>(null);
  const [launchPreview, setLaunchPreview] =
    useState<GreenhouseApplicationLaunchPreview | null>(null);
  const [approveEligibility, setApproveEligibility] = useState(false);
  const [preferredTags, setPreferredTags] = useState("");
  const [preferPrimary, setPreferPrimary] = useState(true);
  const [requirementsDirty, setRequirementsDirty] = useState(false);
  const [findingsDirty, setFindingsDirty] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const generation = useRef(0);
  const active = useRef(false);

  function clearPreviews() {
    setRequirementsPreview(null);
    setQualificationPreview(null);
    setResumePreview(null);
    setLaunchPreview(null);
    setApproveEligibility(false);
  }

  useEffect(() => {
    generation.current += 1;
    active.current = false;
    setSnapshot(null);
    setChoices({});
    setFindings([]);
    clearPreviews();
    setPending(null);
    setError(null);
    setNotice(null);
    setPreferredTags("");
    setPreferPrimary(true);
    setRequirementsDirty(false);
    setFindingsDirty(false);
    return () => {
      generation.current += 1;
    };
  }, [applicationId, profileId, backendReady]);

  function accept(value: JobReadinessSnapshot) {
    if (
      value.application_id !== applicationId ||
      value.profile_id !== profileId
    )
      throw new Error("The saved job does not match the selected application.");
    setSnapshot(value);
    setRequirementsDirty(false);
    setFindingsDirty(false);
    setChoices(
      Object.fromEntries(
        (value.requirements_review?.requirements ?? []).map((item) => [
          item.span_id,
          item.classification,
        ]),
      ),
    );
    setFindings(
      (value.requirements_review?.requirements ?? []).map((item) => {
        const previous = value.qualification_review?.findings.find(
          (finding) => finding.requirement_id === item.id,
        );
        return {
          requirement_id: item.id,
          status: previous?.status ?? "UNKNOWN",
          claim_ids: previous?.claim_ids ?? [],
        };
      }),
    );
    clearPreviews();
  }

  async function run<T>(
    kind: Pending,
    operation: () => Promise<T>,
    success: (value: T) => void | Promise<void>,
  ) {
    if (!backendReady || !applicationId || !profileId || active.current) return;
    const request = ++generation.current;
    active.current = true;
    setPending(kind);
    setError(null);
    setNotice(null);
    try {
      const result = await operation();
      if (generation.current !== request) return;
      await success(result);
    } catch {
      if (generation.current === request) {
        clearPreviews();
        setSnapshot(null);
        setError(
          "The saved job review could not be confirmed. Reload local evidence and review again. No application was submitted.",
        );
      }
    } finally {
      if (generation.current === request) {
        active.current = false;
        setPending(null);
      }
    }
  }

  async function approved(value: JobReadinessSnapshot | null) {
    if (!value) {
      setNotice("Review approval was cancelled. No choice was saved.");
      return;
    }
    accept(value);
    setNotice(
      "Your reviewed choice was saved locally. No application was submitted.",
    );
    const request = generation.current;
    try {
      await onChanged();
    } catch {
      if (generation.current === request)
        setNotice(
          "Your choice is saved, but the workflow queue could not be refreshed. Refresh the queue before continuing.",
        );
    }
  }

  const can = (action: JobReadinessSnapshot["allowed_actions"][number]) =>
    backendReady &&
    !pending &&
    !!snapshot?.supported &&
    snapshot.allowed_actions.includes(action) &&
    (action === "REVIEW_REQUIREMENTS" || !requirementsDirty) &&
    (action !== "SELECT_RESUME" || !findingsDirty);
  const api = window.jobApplyPro.workbench;

  function previewRequirements() {
    if (!can("REVIEW_REQUIREMENTS") || !snapshot?.source_fingerprint) return;
    const input: RequirementsRequest = {
      application_id: snapshot.application_id,
      source_fingerprint: snapshot.source_fingerprint,
      items: snapshot.spans.flatMap((span) =>
        choices[span.id]
          ? [
              {
                span_id: span.id,
                classification: choices[span.id] as RequirementClassification,
              },
            ]
          : [],
      ),
    };
    clearPreviews();
    void run(
      "requirements",
      () => api.previewJobRequirements(input),
      (result) => {
        if (
          result.application_id !== applicationId ||
          result.job_id !== snapshot.job_id ||
          result.source_fingerprint !== input.source_fingerprint
        )
          throw new Error("Mismatched review");
        setRequirementsPreview({ input, result });
      },
    );
  }

  function previewQualification() {
    if (!can("REVIEW_QUALIFICATION") || !snapshot?.requirements_review) return;
    const input: QualificationRequest = {
      application_id: snapshot.application_id,
      requirements_review_id: snapshot.requirements_review.id,
      findings,
    };
    clearPreviews();
    void run(
      "qualification",
      () => api.previewJobQualification(input),
      (result) => {
        if (
          result.application_id !== applicationId ||
          result.requirements_review_id !== input.requirements_review_id
        )
          throw new Error("Mismatched review");
        setQualificationPreview({ input, result });
      },
    );
  }

  function previewResume() {
    if (!can("SELECT_RESUME") || !snapshot) return;
    const input: DocumentSelectionRequest = {
      application_id: snapshot.application_id,
      kind: "RESUME",
      preferred_tags: preferredTags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      excluded_document_ids: [],
      prefer_primary: preferPrimary,
    };
    clearPreviews();
    void run(
      "resume",
      () => api.previewJobResume(input),
      (result) => {
        if (
          result.selection.application_id !== applicationId ||
          result.selection.profile_id !== profileId ||
          result.requirements_review_id !== snapshot.requirements_review?.id ||
          result.qualification_review_id !== snapshot.qualification_review?.id
        )
          throw new Error("Mismatched review");
        setResumePreview({ input, result });
      },
    );
  }

  function previewGreenhouseLaunch() {
    if (!snapshot || snapshot.status !== "READY") return;
    setLaunchPreview(null);
    void run(
      "launch-preview",
      () => api.previewGreenhouseApplicationLaunch(snapshot.application_id),
      (result) => {
        if (
          result.application_id !== applicationId ||
          result.profile_id !== profileId ||
          result.workflow_id !== snapshot.workflow_id ||
          result.source_fingerprint !== snapshot.source_fingerprint ||
          result.selected_document_version_id !==
            snapshot.selection_review?.document_version_id
        )
          throw new Error("Mismatched Greenhouse launch review");
        setLaunchPreview(result);
      },
    );
  }

  function startGreenhouseLaunch() {
    if (!launchPreview) return;
    void run(
      "launch",
      () =>
        api.startGreenhouseApplicationLaunch({
          application_id: launchPreview.application_id,
          review_fingerprint: launchPreview.review_fingerprint,
          profile_name: "greenhouse-profile",
          engine: "msedge",
        }),
      async (result) => {
        if (!result) {
          setNotice(
            "Greenhouse launch was cancelled. No browser was opened and no application was submitted.",
          );
          return;
        }
        if (
          result.portal !== "GREENHOUSE" ||
          result.workflow_id !== launchPreview.workflow_id
        )
          throw new Error("Mismatched Greenhouse portal run");
        setNotice(
          "The reviewed Greenhouse posting is open in a visible supervised browser. No application was submitted.",
        );
        await onPortalStarted?.(result);
      },
    );
  }

  function updateFinding(id: string, change: Partial<RequirementFinding>) {
    clearPreviews();
    setFindingsDirty(true);
    setFindings((current) =>
      current.map((item) =>
        item.requirement_id === id ? { ...item, ...change } : item,
      ),
    );
  }

  const displayedQualification =
    qualificationPreview?.result ?? snapshot?.qualification_review;
  return (
    <section
      className="panel job-readiness-panel"
      id="job-readiness"
      aria-labelledby="job-readiness-title"
      aria-busy={!!pending}
    >
      <div className="panel__header">
        <div>
          <h2 id="job-readiness-title">Reviewed job readiness</h2>
          <p>
            Review the selected application's saved source, claim evidence, and
            immutable resume. Local evidence coverage is not a hiring
            probability or an employer verification.
          </p>
        </div>
      </div>
      <p>
        {applicationId
          ? `Selected application: ${applicationId} · Profile: ${profileId ?? "None"}`
          : "Select an imported job in the workflow queue."}
      </p>
      <button
        className="button button--secondary"
        type="button"
        disabled={!backendReady || !applicationId || !profileId || !!pending}
        onClick={() => {
          clearPreviews();
          void run("load", () => api.getJobReadiness(applicationId!), accept);
        }}
      >
        Load saved job evidence
      </button>
      <p>
        No live job-board request, browser action, or provider call is made by
        this panel.
      </p>
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {snapshot && (
        <>
          <p role="status">
            Review status: {snapshot.status.replaceAll("_", " ").toLowerCase()}.{" "}
            {snapshot.notice}
          </p>
          {(requirementsDirty || findingsDirty) && (
            <p role="status">
              You have unsaved review changes. Approve them, or reload saved
              evidence, before continuing to later steps.
            </p>
          )}
          {snapshot.source && (
            <article>
              <h3>
                {snapshot.source.title} at {snapshot.source.employer}
              </h3>
              <p>Saved public source: {snapshot.source.api_url}</p>
              <p>Reported posting URL: {snapshot.source.reported_url}</p>
              <p>
                Fetched: {snapshot.source.fetched_at} · Normalizer:{" "}
                {snapshot.source.normalizer_version}
              </p>
              <p>
                Saved source fingerprint:{" "}
                <code>{snapshot.source_fingerprint}</code>
              </p>
              <details>
                <summary>Read the full saved posting</summary>
                <pre>{snapshot.source.description}</pre>
              </details>
            </article>
          )}
          {snapshot.supported && (
            <>
              <h3>1. Review source requirements</h3>
              <p>
                Select exact source passages and classify them yourself.
                Unselected passages are excluded; ambiguous requirements prevent
                eligibility clearance. Source text cannot be rewritten here.
              </p>
              <fieldset disabled={!can("REVIEW_REQUIREMENTS")}>
                <legend>Exact saved source passages</legend>
                {snapshot.spans.map((span, index) => (
                  <div className="answer-entry" key={span.id}>
                    <pre>{span.text}</pre>
                    <label>
                      Classification for passage {index + 1}
                      <select
                        value={choices[span.id] ?? ""}
                        onChange={(event) => {
                          clearPreviews();
                          setRequirementsDirty(true);
                          setChoices((current) => ({
                            ...current,
                            [span.id]: event.target.value as
                              RequirementClassification | "",
                          }));
                        }}
                      >
                        <option value="">Not a selected requirement</option>
                        <option value="MANDATORY">Mandatory</option>
                        <option value="PREFERRED">Preferred</option>
                        <option value="AMBIGUOUS">
                          Ambiguous — needs clarification
                        </option>
                      </select>
                    </label>
                  </div>
                ))}
                <button
                  className="button button--secondary"
                  type="button"
                  onClick={previewRequirements}
                >
                  Preview source requirements
                </button>
              </fieldset>
              {requirementsPreview && (
                <article className="answer-entry">
                  <h4>Exact requirements approval preview</h4>
                  {requirementsPreview.result.requirements.map((item) => (
                    <p key={item.id}>
                      {item.classification}: {item.text}
                    </p>
                  ))}
                  {!requirementsPreview.result.requirements.length && (
                    <p>
                      No requirements selected. This cannot establish
                      eligibility.
                    </p>
                  )}
                  <p>{requirementsPreview.result.notice}</p>
                  <button
                    className="button button--primary"
                    type="button"
                    disabled={!!pending}
                    onClick={() =>
                      void run(
                        "approval",
                        () =>
                          api.approveJobRequirements({
                            input: requirementsPreview.input,
                            review_fingerprint:
                              requirementsPreview.result.review_fingerprint,
                          }),
                        approved,
                      )
                    }
                  >
                    Review & approve requirements
                  </button>
                </article>
              )}
              {snapshot.requirements_review && (
                <>
                  <p>
                    Saved requirements revision{" "}
                    {snapshot.requirements_review.revision} ·{" "}
                    {snapshot.requirements_review.created_at}
                  </p>
                  <h3>2. Review claim evidence and eligibility</h3>
                  <p>
                    Evidence links are your reviewed assessment. A claim's
                    presence or a keyword match does not automatically satisfy a
                    requirement. Only current, locked, application-approved
                    claims are offered.
                  </p>
                  <fieldset disabled={!can("REVIEW_QUALIFICATION")}>
                    <legend>Per-requirement findings</legend>
                    {snapshot.requirements_review.requirements.map(
                      (item, index) => {
                        const finding = findings.find(
                          (value) => value.requirement_id === item.id,
                        );
                        return (
                          <article className="answer-entry" key={item.id}>
                            <strong>
                              {item.classification}: {item.text}
                            </strong>
                            <label>
                              Evidence finding for requirement {index + 1}
                              <select
                                value={finding?.status ?? "UNKNOWN"}
                                onChange={(event) =>
                                  updateFinding(item.id, {
                                    status: event.target.value as FindingStatus,
                                    claim_ids: [],
                                  })
                                }
                              >
                                <option value="UNKNOWN">
                                  Unknown / insufficient evidence
                                </option>
                                <option value="SUPPORTED">
                                  Supported by reviewed claims
                                </option>
                                <option value="CONTRADICTED">
                                  Contradicted by reviewed claims
                                </option>
                              </select>
                            </label>
                            <fieldset
                              disabled={
                                !finding || finding.status === "UNKNOWN"
                              }
                            >
                              <legend>
                                Reviewed claim links for requirement {index + 1}
                              </legend>
                              {snapshot.evidence_claims.map((claim) => (
                                <label className="checkbox-row" key={claim.id}>
                                  <input
                                    type="checkbox"
                                    checked={
                                      finding?.claim_ids.includes(claim.id) ??
                                      false
                                    }
                                    onChange={(event) =>
                                      updateFinding(item.id, {
                                        claim_ids: event.target.checked
                                          ? [
                                              ...(finding?.claim_ids ?? []),
                                              claim.id,
                                            ]
                                          : (finding?.claim_ids ?? []).filter(
                                              (id) => id !== claim.id,
                                            ),
                                      })
                                    }
                                  />
                                  {claim.statement} · Claim {claim.id}
                                </label>
                              ))}
                              {!snapshot.evidence_claims.length && (
                                <p>
                                  No current approved claim evidence is
                                  available. Keep this finding unknown.
                                </p>
                              )}
                            </fieldset>
                          </article>
                        );
                      },
                    )}
                    <button
                      className="button button--secondary"
                      type="button"
                      disabled={findings.some(
                        (item) =>
                          item.status !== "UNKNOWN" && !item.claim_ids.length,
                      )}
                      onClick={previewQualification}
                    >
                      Preview evidence assessment
                    </button>
                  </fieldset>
                </>
              )}
              {displayedQualification && (
                <article className="answer-entry">
                  <h4>Evidence coverage — not hiring probability</h4>
                  <p>
                    {displayedQualification.mandatory_supported} of{" "}
                    {displayedQualification.mandatory_count} mandatory
                    requirements supported;{" "}
                    {displayedQualification.preferred_supported} of{" "}
                    {displayedQualification.preferred_count} preferred
                    requirements supported.
                  </p>
                  <p>
                    {displayedQualification.coverage_score === null
                      ? "Coverage is not evaluable."
                      : `Reviewed evidence coverage: ${Math.round(displayedQualification.coverage_score * 100)}%.`}
                  </p>
                  <p>{displayedQualification.notice}</p>
                  <p>Policy: {displayedQualification.policy_version}</p>
                  {qualificationPreview ? (
                    <>
                      {qualificationPreview.result.findings.map((item) => (
                        <p key={item.requirement_id}>
                          {item.status}: {item.text} · {item.claim_ids.length}{" "}
                          reviewed claim links
                        </p>
                      ))}
                      <label className="checkbox-row">
                        <input
                          type="checkbox"
                          checked={approveEligibility}
                          disabled={
                            !!pending ||
                            !qualificationPreview.result.evaluable ||
                            !qualificationPreview.result.eligible
                          }
                          onChange={(event) =>
                            setApproveEligibility(event.target.checked)
                          }
                        />
                        I reviewed these local criteria and approve eligibility
                        to continue to resume selection
                      </label>
                      <button
                        className="button button--primary"
                        type="button"
                        disabled={!!pending}
                        onClick={() =>
                          void run(
                            "approval",
                            () =>
                              api.approveJobQualification({
                                input: qualificationPreview.input,
                                review_fingerprint:
                                  qualificationPreview.result
                                    .review_fingerprint,
                                approve_eligibility: approveEligibility,
                              }),
                            approved,
                          )
                        }
                      >
                        Review & save qualification decision
                      </button>
                    </>
                  ) : (
                    <p>
                      {snapshot.status === "STALE"
                        ? "This saved assessment is stale and does not provide current eligibility clearance."
                        : snapshot.qualification_review?.eligibility_approved
                          ? "Eligibility was explicitly approved against these local criteria."
                          : "No eligibility clearance was approved."}
                    </p>
                  )}
                </article>
              )}
              <h3>3. Review and select an immutable resume</h3>
              <p>
                Resume ranking describes document relevance, not candidate
                eligibility. Selection requires a separate native confirmation.
              </p>
              <fieldset disabled={!can("SELECT_RESUME")}>
                <legend>Resume ranking preferences</legend>
                <label>
                  Preferred resume tags
                  <input
                    value={preferredTags}
                    maxLength={1000}
                    onChange={(event) => {
                      setPreferredTags(event.target.value);
                      setResumePreview(null);
                    }}
                  />
                </label>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={preferPrimary}
                    onChange={(event) => {
                      setPreferPrimary(event.target.checked);
                      setResumePreview(null);
                    }}
                  />
                  Consider primary-resume preference
                </label>
                <button
                  className="button button--secondary"
                  type="button"
                  onClick={previewResume}
                >
                  Preview readiness resume ranking
                </button>
              </fieldset>
              {resumePreview && (
                <article>
                  <p>{resumePreview.result.notice}</p>
                  {resumePreview.result.selection.recommendations.map(
                    (item, index) => (
                      <div
                        className="answer-entry"
                        key={item.document_version_id}
                      >
                        <strong>
                          {index + 1}. {item.variant_label} ·{" "}
                          {item.display_name}
                        </strong>
                        <p>
                          Document relevance score:{" "}
                          {Math.round(item.score * 100)}% ·{" "}
                          {item.matched_requirement_ids.length} matched source
                          requirements
                        </p>
                        <p>Immutable version: {item.document_version_id}</p>
                        <ul>
                          {item.reasons.map((reason) => (
                            <li key={reason}>{reason}</li>
                          ))}
                        </ul>
                        <button
                          className="button button--primary"
                          type="button"
                          disabled={!!pending}
                          onClick={() =>
                            void run(
                              "approval",
                              () =>
                                api.approveJobResume({
                                  input: resumePreview.input,
                                  review_fingerprint:
                                    resumePreview.result.review_fingerprint,
                                  document_version_id: item.document_version_id,
                                }),
                              approved,
                            )
                          }
                        >
                          Review & select {item.variant_label}
                        </button>
                      </div>
                    ),
                  )}
                </article>
              )}
              {snapshot.selection_review && (
                <p>
                  Saved resume choice: immutable version{" "}
                  {snapshot.selection_review.document_version_id} · Selection
                  revision {snapshot.selection_review.revision}. This is not an
                  upload or application submission.
                </p>
              )}
              {snapshot.status === "READY" && (
                <article className="answer-entry">
                  <h3>4. Open the reviewed Greenhouse application</h3>
                  <p>
                    The backend will recheck the saved posting, eligibility
                    reviews, and immutable resume before it derives the exact
                    Greenhouse URL and origin.
                  </p>
                  <button
                    className="button button--secondary"
                    type="button"
                    disabled={!!pending}
                    onClick={previewGreenhouseLaunch}
                  >
                    Review Greenhouse launch
                  </button>
                  {launchPreview && (
                    <div>
                      <p>
                        {launchPreview.title} at {launchPreview.employer}
                      </p>
                      <p>Exact start URL: {launchPreview.start_url}</p>
                      <p>Exact allowed origin: {launchPreview.start_origin}</p>
                      <p>
                        Immutable resume version:{" "}
                        {launchPreview.selected_document_version_id}
                      </p>
                      <p>
                        Launch review fingerprint:{" "}
                        <code>{launchPreview.review_fingerprint}</code>
                      </p>
                      <p>{launchPreview.notice}</p>
                      <button
                        className="button button--primary"
                        type="button"
                        disabled={!!pending}
                        onClick={startGreenhouseLaunch}
                      >
                        Open reviewed Greenhouse application
                      </button>
                    </div>
                  )}
                </article>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
