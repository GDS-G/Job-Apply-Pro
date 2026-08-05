import pytest
from sqlalchemy.orm import Session

from job_apply_pro.domain.workflow import (
    InvalidTransitionError,
    TransitionCommand,
    VerificationResult,
    WorkflowState,
    validate_transition,
)
from job_apply_pro.services.workflows import WorkflowService
from job_apply_pro.storage.repositories import WorkflowEventRepository


def test_primary_transition_is_allowed() -> None:
    validate_transition(
        TransitionCommand(
            current_state=WorkflowState.DISCOVERED,
            next_state=WorkflowState.DEDUPLICATED,
            actor="orchestrator",
            cause="Canonical job identity was computed.",
        )
    )


def test_confirmed_submission_requires_passed_verification() -> None:
    command = TransitionCommand(
        current_state=WorkflowState.SUBMISSION_ATTEMPTED,
        next_state=WorkflowState.SUBMISSION_CONFIRMED,
        actor="verification-agent",
        cause="Submit action returned without confirmation evidence.",
        verification=VerificationResult.UNCERTAIN,
    )

    with pytest.raises(InvalidTransitionError):
        validate_transition(command)


def test_service_persists_ordered_append_only_events(session: Session) -> None:
    service = WorkflowService(WorkflowEventRepository(session))
    command = TransitionCommand(
        current_state=WorkflowState.DISCOVERED,
        next_state=WorkflowState.DEDUPLICATED,
        actor="orchestrator",
        cause="No existing canonical job matched.",
    )

    event = service.transition("workflow-1", command)
    history = service.history("workflow-1")

    assert event.sequence == 1
    assert history == [event]
