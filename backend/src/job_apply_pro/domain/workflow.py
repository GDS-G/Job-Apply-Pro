from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field


class WorkflowState(StrEnum):
    DISCOVERED = "DISCOVERED"
    DEDUPLICATED = "DEDUPLICATED"
    SCORED = "SCORED"
    ELIGIBILITY_CHECKED = "ELIGIBILITY_CHECKED"
    DOCUMENTS_SELECTED = "DOCUMENTS_SELECTED"
    APPLICATION_OPENED = "APPLICATION_OPENED"
    FORM_MAPPED = "FORM_MAPPED"
    ANSWERS_VALIDATED = "ANSWERS_VALIDATED"
    ASSESSMENT_PENDING = "ASSESSMENT_PENDING"
    ASSESSMENT_IN_PROGRESS = "ASSESSMENT_IN_PROGRESS"
    ASSESSMENT_COMPLETED = "ASSESSMENT_COMPLETED"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMISSION_ATTEMPTED = "SUBMISSION_ATTEMPTED"
    SUBMISSION_CONFIRMED = "SUBMISSION_CONFIRMED"
    TRACKING_ACTIVE = "TRACKING_ACTIVE"
    CLOSED = "CLOSED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    MFA_REQUIRED = "MFA_REQUIRED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    UNKNOWN_QUESTION = "UNKNOWN_QUESTION"
    SENSITIVE_FIELD = "SENSITIVE_FIELD"
    ASSESSMENT_REQUIRED = "ASSESSMENT_REQUIRED"
    SITE_CHANGED = "SITE_CHANGED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    POLICY_REVIEW = "POLICY_REVIEW"
    USER_TAKEOVER = "USER_TAKEOVER"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"


class VerificationResult(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


INTERRUPTION_STATES = frozenset(
    {
        WorkflowState.LOGIN_REQUIRED,
        WorkflowState.MFA_REQUIRED,
        WorkflowState.CAPTCHA_REQUIRED,
        WorkflowState.UNKNOWN_QUESTION,
        WorkflowState.SENSITIVE_FIELD,
        WorkflowState.ASSESSMENT_REQUIRED,
        WorkflowState.SITE_CHANGED,
        WorkflowState.SESSION_EXPIRED,
        WorkflowState.POLICY_REVIEW,
        WorkflowState.USER_TAKEOVER,
        WorkflowState.SUBMISSION_UNCERTAIN,
        WorkflowState.FAILED_RETRYABLE,
        WorkflowState.FAILED_TERMINAL,
    }
)

_PRIMARY_FLOW = (
    WorkflowState.DISCOVERED,
    WorkflowState.DEDUPLICATED,
    WorkflowState.SCORED,
    WorkflowState.ELIGIBILITY_CHECKED,
    WorkflowState.DOCUMENTS_SELECTED,
    WorkflowState.APPLICATION_OPENED,
    WorkflowState.FORM_MAPPED,
    WorkflowState.ANSWERS_VALIDATED,
    WorkflowState.READY_TO_SUBMIT,
    WorkflowState.SUBMISSION_ATTEMPTED,
    WorkflowState.SUBMISSION_CONFIRMED,
    WorkflowState.TRACKING_ACTIVE,
    WorkflowState.CLOSED,
)


def _build_transitions() -> Mapping[WorkflowState, frozenset[WorkflowState]]:
    transitions: dict[WorkflowState, set[WorkflowState]] = {
        state: set(INTERRUPTION_STATES)
        for state in WorkflowState
        if state is not WorkflowState.CLOSED
    }
    for current, next_state in pairwise(_PRIMARY_FLOW):
        transitions[current].add(next_state)
    transitions[WorkflowState.ANSWERS_VALIDATED].add(WorkflowState.ASSESSMENT_PENDING)
    transitions[WorkflowState.ASSESSMENT_PENDING].add(WorkflowState.ASSESSMENT_IN_PROGRESS)
    transitions[WorkflowState.ASSESSMENT_IN_PROGRESS].add(WorkflowState.ASSESSMENT_COMPLETED)
    transitions[WorkflowState.ASSESSMENT_COMPLETED].add(WorkflowState.READY_TO_SUBMIT)
    for state in INTERRUPTION_STATES - {WorkflowState.FAILED_TERMINAL}:
        transitions[state].update(_PRIMARY_FLOW)
    transitions[WorkflowState.SUBMISSION_ATTEMPTED].update(
        {WorkflowState.SUBMISSION_CONFIRMED, WorkflowState.SUBMISSION_UNCERTAIN}
    )
    transitions[WorkflowState.FAILED_TERMINAL] = {WorkflowState.CLOSED}
    transitions[WorkflowState.CLOSED] = set()
    return {state: frozenset(targets) for state, targets in transitions.items()}


ALLOWED_TRANSITIONS = _build_transitions()


class InvalidTransitionError(ValueError):
    def __init__(self, current: WorkflowState, target: WorkflowState) -> None:
        super().__init__(f"Transition from {current} to {target} is not allowed")
        self.current = current
        self.target = target


class TransitionCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_state: WorkflowState
    next_state: WorkflowState
    actor: str = Field(min_length=1, max_length=100)
    cause: str = Field(min_length=1, max_length=500)
    verification: VerificationResult = VerificationResult.NOT_REQUIRED
    retry_count: int = Field(default=0, ge=0, le=20)


class WorkflowEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    workflow_id: str
    sequence: int
    prior_state: WorkflowState
    next_state: WorkflowState
    actor: str
    cause: str
    verification: VerificationResult
    retry_count: int
    occurred_at: datetime


def validate_transition(command: TransitionCommand) -> None:
    if command.next_state not in ALLOWED_TRANSITIONS[command.current_state]:
        raise InvalidTransitionError(command.current_state, command.next_state)
    if (
        command.next_state is WorkflowState.SUBMISSION_CONFIRMED
        and command.verification is not VerificationResult.PASSED
    ):
        raise InvalidTransitionError(command.current_state, command.next_state)


def utc_now() -> datetime:
    return datetime.now(UTC)
