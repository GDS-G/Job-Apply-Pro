import {
  AlertTriangle,
  ArrowRight,
  BriefcaseBusiness,
  FileCheck2,
  FileQuestion,
  Mail,
  ShieldCheck,
} from "lucide-react";

import type { WorkflowRunSnapshot } from "@job-apply-pro/contracts";

interface ApplicationWorkspaceGuideProps {
  workflow: WorkflowRunSnapshot | null;
  documentCount: number;
  answerCount: number;
  fieldBindingCount: number;
  portalStatus: string | null;
  challengeStatus: string | null;
  messageCount: number;
  unresolvedBrowserEffectCount: number;
  onNavigate: (sectionId: string) => void;
}

interface WorkspaceStep {
  id: string;
  label: string;
  detail: string;
  icon: typeof BriefcaseBusiness;
}

const APPLICATION_STATES = new Set([
  "DOCUMENTS_SELECTED",
  "APPLICATION_OPENED",
  "FORM_MAPPED",
  "ANSWERS_VALIDATED",
  "READY_TO_SUBMIT",
  "USER_TAKEOVER",
  "FAILED_RETRYABLE",
]);

const FOLLOW_UP_STATES = new Set([
  "SUBMISSION_ATTEMPTED",
  "SUBMISSION_CONFIRMED",
  "TRACKING_ACTIVE",
  "CLOSED",
]);

function suggestedTarget(
  workflow: WorkflowRunSnapshot | null,
  documentCount: number,
  challengeStatus: string | null,
  unresolvedBrowserEffectCount: number,
): string {
  if (unresolvedBrowserEffectCount > 0) return "operations-recovery";
  if (
    challengeStatus &&
    !["COMPLETED", "FAILED", "EXPIRED"].includes(challengeStatus)
  ) {
    return "challenge-framework";
  }
  if (!workflow) return "job-discovery";
  if (documentCount === 0) return "candidate-evidence";
  if (workflow.state === "FAILED_TERMINAL") return "operations-recovery";
  if (FOLLOW_UP_STATES.has(workflow.state)) return "communication-scheduling";
  if (APPLICATION_STATES.has(workflow.state)) return "application-portal";
  return "job-readiness";
}

export function ApplicationWorkspaceGuide({
  workflow,
  documentCount,
  answerCount,
  fieldBindingCount,
  portalStatus,
  challengeStatus,
  messageCount,
  unresolvedBrowserEffectCount,
  onNavigate,
}: ApplicationWorkspaceGuideProps) {
  const firstStepTarget = workflow ? "job-readiness" : "job-discovery";
  const steps: WorkspaceStep[] = [
    {
      id: firstStepTarget,
      label: "Job & readiness",
      detail: workflow
        ? `Backend state: ${workflow.state.replaceAll("_", " ")}`
        : "No application selected",
      icon: BriefcaseBusiness,
    },
    {
      id: "candidate-evidence",
      label: "Documents & evidence",
      detail: `${documentCount} candidate document${documentCount === 1 ? "" : "s"}`,
      icon: FileCheck2,
    },
    {
      id: "application-portal",
      label: "Application & fields",
      detail: `${answerCount} answer${answerCount === 1 ? "" : "s"} · ${fieldBindingCount} binding${fieldBindingCount === 1 ? "" : "s"} · ${portalStatus?.replaceAll("_", " ") ?? "no selected run"}`,
      icon: FileQuestion,
    },
    {
      id: "challenge-framework",
      label: "Challenges",
      detail: challengeStatus?.replaceAll("_", " ") ?? "No active challenge",
      icon: ShieldCheck,
    },
    {
      id: "communication-scheduling",
      label: "Follow-up",
      detail: `${messageCount} correlated message${messageCount === 1 ? "" : "s"}`,
      icon: Mail,
    },
  ];
  const target = suggestedTarget(
    workflow,
    documentCount,
    challengeStatus,
    unresolvedBrowserEffectCount,
  );

  return (
    <section
      aria-labelledby="application-workspace-guide-title"
      className="panel application-workspace-guide"
    >
      <div className="application-workspace-guide__summary">
        <span className="eyebrow">Selected application path</span>
        <h2 id="application-workspace-guide-title">
          Guided application workspace
        </h2>
        {workflow ? (
          <>
            <strong>
              {workflow.title} at {workflow.employer}
            </strong>
            <p>
              {workflow.candidate_display_name} · Saved state {workflow.state} ·
              Application {workflow.application_id}
            </p>
          </>
        ) : (
          <p>
            Discover or create an application workflow to bind every workspace
            view to one saved record.
          </p>
        )}
        <small>
          Navigation only; backend state, allowed actions, review fingerprints,
          and provider gates remain authoritative.
        </small>
      </div>

      <div className="application-workspace-guide__steps">
        {steps.map((step) => {
          const Icon = step.icon;
          const suggested = target === step.id;
          return (
            <button
              className={
                suggested
                  ? "workspace-step workspace-step--suggested"
                  : "workspace-step"
              }
              key={step.label}
              onClick={() => onNavigate(step.id)}
              type="button"
            >
              <Icon size={17} />
              <span>
                <strong>{step.label}</strong>
                <small>{step.detail}</small>
              </span>
              {suggested ? <em>Suggested</em> : <ArrowRight size={14} />}
            </button>
          );
        })}
      </div>

      {unresolvedBrowserEffectCount > 0 ? (
        <button
          className="application-workspace-guide__warning"
          onClick={() => onNavigate("operations-recovery")}
          type="button"
        >
          <AlertTriangle size={17} />
          <span>
            <strong>
              {unresolvedBrowserEffectCount} selected-browser effect
              {unresolvedBrowserEffectCount === 1 ? "" : "s"} need
              reconciliation
            </strong>
            <small>
              Open Operations to inspect evidence. This workspace does not retry
              or clear an uncertain effect.
            </small>
          </span>
          <ArrowRight size={14} />
        </button>
      ) : null}
    </section>
  );
}
