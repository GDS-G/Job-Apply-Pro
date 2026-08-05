import hashlib
from uuid import uuid4

from job_apply_pro.domain.applications import ApplicationCreate
from job_apply_pro.domain.jobs import JobCreate
from job_apply_pro.domain.workbench import (
    MockWorkflowCreate,
    WorkflowControlAction,
    WorkflowControlCommand,
    WorkflowRunSnapshot,
)
from job_apply_pro.domain.workflow import TransitionCommand, WorkflowState
from job_apply_pro.storage.repository_contracts import (
    ApplicationRepositoryProtocol,
    CandidateRepositoryProtocol,
    JobRepositoryProtocol,
    WorkbenchRepositoryProtocol,
)


class WorkbenchStateError(ValueError):
    pass


_ADVANCE_TARGETS: dict[WorkflowState, WorkflowState] = {
    WorkflowState.DISCOVERED: WorkflowState.DEDUPLICATED,
    WorkflowState.DEDUPLICATED: WorkflowState.SCORED,
    WorkflowState.SCORED: WorkflowState.ELIGIBILITY_CHECKED,
    WorkflowState.ELIGIBILITY_CHECKED: WorkflowState.DOCUMENTS_SELECTED,
    WorkflowState.DOCUMENTS_SELECTED: WorkflowState.APPLICATION_OPENED,
    WorkflowState.APPLICATION_OPENED: WorkflowState.FORM_MAPPED,
    WorkflowState.FORM_MAPPED: WorkflowState.ANSWERS_VALIDATED,
    WorkflowState.ANSWERS_VALIDATED: WorkflowState.READY_TO_SUBMIT,
}


class WorkbenchService:
    def __init__(
        self,
        candidates: CandidateRepositoryProtocol,
        jobs: JobRepositoryProtocol,
        applications: ApplicationRepositoryProtocol,
        workbench: WorkbenchRepositoryProtocol,
    ) -> None:
        self._candidates = candidates
        self._jobs = jobs
        self._applications = applications
        self._workbench = workbench

    def start_mock_workflow(self, command: MockWorkflowCreate) -> WorkflowRunSnapshot:
        if self._candidates.get_encrypted(command.profile_id) is None:
            raise LookupError(f"Candidate profile {command.profile_id} was not found")
        workflow_id = f"mock-{uuid4()}"
        identity = f"{command.employer}\n{command.title}\n{workflow_id}".encode()
        job = self._jobs.add(
            JobCreate(
                source="workbench-mock",
                external_id=workflow_id,
                employer=command.employer,
                title=command.title,
                description_hash=hashlib.sha256(identity).hexdigest(),
            )
        )
        self._applications.add(
            ApplicationCreate(
                workflow_id=workflow_id,
                profile_id=command.profile_id,
                job_id=job.id,
            )
        )
        return self._workbench.apply_transition(
            workflow_id,
            TransitionCommand(
                current_state=WorkflowState.DISCOVERED,
                next_state=WorkflowState.DEDUPLICATED,
                actor="workbench",
                cause="Mock workflow started and canonical job identity was verified.",
            ),
        )

    def list_workflows(self) -> list[WorkflowRunSnapshot]:
        return self._workbench.list_snapshots()

    def get_workflow(self, workflow_id: str) -> WorkflowRunSnapshot:
        snapshot = self._workbench.get_snapshot(workflow_id)
        if snapshot is None:
            raise LookupError(f"Workflow {workflow_id} was not found")
        return snapshot

    def control_workflow(
        self, workflow_id: str, command: WorkflowControlCommand
    ) -> WorkflowRunSnapshot:
        snapshot = self.get_workflow(workflow_id)
        target, cause = self._resolve_target(snapshot, command.action)
        return self._workbench.apply_transition(
            workflow_id,
            TransitionCommand(
                current_state=snapshot.state,
                next_state=target,
                actor="desktop-user",
                cause=cause,
                retry_count=1 if command.action is WorkflowControlAction.RETRY else 0,
            ),
        )

    def _resolve_target(
        self, snapshot: WorkflowRunSnapshot, action: WorkflowControlAction
    ) -> tuple[WorkflowState, str]:
        current = snapshot.state
        if action is WorkflowControlAction.ADVANCE:
            target = _ADVANCE_TARGETS.get(current)
            if target is None:
                raise WorkbenchStateError(f"Workflow cannot advance from {current}")
            return target, "User advanced the supervised mock workflow."
        if action in {WorkflowControlAction.PAUSE, WorkflowControlAction.TAKEOVER}:
            if current is WorkflowState.USER_TAKEOVER:
                raise WorkbenchStateError("Workflow is already paused for user takeover")
            return WorkflowState.USER_TAKEOVER, "User paused the workflow for manual takeover."
        if action is WorkflowControlAction.RESUME:
            if current is not WorkflowState.USER_TAKEOVER:
                raise WorkbenchStateError("Only a paused workflow can resume")
            prior = snapshot.events[-1].prior_state if snapshot.events else WorkflowState.DISCOVERED
            return prior, "User returned control to the supervised workflow."
        if action is WorkflowControlAction.RETRY:
            if current is WorkflowState.FAILED_RETRYABLE:
                return WorkflowState.DEDUPLICATED, "User retried the recoverable workflow."
            return WorkflowState.FAILED_RETRYABLE, "User requested a recoverable retry checkpoint."
        if action is WorkflowControlAction.STOP:
            if current is WorkflowState.FAILED_TERMINAL:
                return WorkflowState.CLOSED, "User closed the stopped workflow."
            if current is WorkflowState.CLOSED:
                raise WorkbenchStateError("Workflow is already closed")
            return WorkflowState.FAILED_TERMINAL, "User stopped the mock workflow."
        raise WorkbenchStateError(f"Unsupported workflow action {action}")
