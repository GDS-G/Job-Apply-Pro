from uuid import uuid4

from job_apply_pro.domain.workflow import (
    TransitionCommand,
    WorkflowEvent,
    utc_now,
    validate_transition,
)
from job_apply_pro.storage.repositories import WorkflowEventRepository


class WorkflowService:
    def __init__(self, repository: WorkflowEventRepository) -> None:
        self._repository = repository

    def transition(self, workflow_id: str, command: TransitionCommand) -> WorkflowEvent:
        validate_transition(command)
        event = WorkflowEvent(
            id=str(uuid4()),
            workflow_id=workflow_id,
            sequence=self._repository.next_sequence(workflow_id),
            prior_state=command.current_state,
            next_state=command.next_state,
            actor=command.actor,
            cause=command.cause,
            verification=command.verification,
            retry_count=command.retry_count,
            occurred_at=utc_now(),
        )
        return self._repository.add(event)

    def history(self, workflow_id: str) -> list[WorkflowEvent]:
        return self._repository.list_for_workflow(workflow_id)
