from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from job_apply_pro.domain.ai import AICapability, AITaskType
from job_apply_pro.domain.workflow import WorkflowState


class ChallengeKind(StrEnum):
    CAPTCHA = "CAPTCHA"
    QUESTIONNAIRE = "QUESTIONNAIRE"
    ASSESSMENT = "ASSESSMENT"
    QUIZ = "QUIZ"


class CaptchaType(StrEnum):
    IMAGE = "IMAGE"
    AUDIO = "AUDIO"
    INTERACTIVE = "INTERACTIVE"
    TOKEN = "TOKEN"
    EMBEDDED = "EMBEDDED"
    UNKNOWN = "UNKNOWN"


class ChallengeStatus(StrEnum):
    DETECTED = "DETECTED"
    INTERVENTION_REQUIRED = "INTERVENTION_REQUIRED"
    IN_PROGRESS = "IN_PROGRESS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class QuestionKind(StrEnum):
    TEXT = "TEXT"
    LONG_TEXT = "LONG_TEXT"
    SELECT = "SELECT"
    CHECKBOX = "CHECKBOX"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    TRUE_FALSE = "TRUE_FALSE"
    MATCHING = "MATCHING"
    ORDERING = "ORDERING"
    VISUAL = "VISUAL"


class AnswerSource(StrEnum):
    CANDIDATE_PROFILE = "CANDIDATE_PROFILE"
    ANSWER_LIBRARY = "ANSWER_LIBRARY"
    USER = "USER"
    AI_GATEWAY = "AI_GATEWAY"


class ChallengeModelTier(StrEnum):
    FAST_TEXT = "FAST_TEXT"
    STRONG_REASONING = "STRONG_REASONING"
    MULTIMODAL = "MULTIMODAL"
    LONG_CONTEXT = "LONG_CONTEXT"


class ChallengeDetection(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ChallengeKind
    page_type: str = Field(min_length=1, max_length=100)
    provider: str | None = Field(default=None, max_length=100)
    captcha_type: CaptchaType | None = None
    signatures: list[str] = Field(default_factory=list, max_length=20)
    page_fingerprint: str = Field(min_length=1, max_length=200)
    detected_at: datetime


class ChallengeQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    position: int = Field(ge=1)
    prompt: str = Field(min_length=1, max_length=2_000)
    kind: QuestionKind
    options: list[str] = Field(default_factory=list, max_length=100)
    required: bool = False
    character_limit: int | None = Field(default=None, ge=1, le=100_000)
    canonical_field: str | None = Field(default=None, max_length=160)
    legal_attestation: bool = False
    signature_required: bool = False


class ChallengeAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    value: str = Field(max_length=100_000)
    source: AnswerSource
    provenance: dict[str, object] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    verified: bool
    answered_at: datetime


class ChallengeSessionCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(min_length=1, max_length=100)
    browser_session_id: str = Field(min_length=1, max_length=100)
    time_limit_seconds: int | None = Field(default=None, ge=30, le=28_800)


class ChallengeAnswerCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str = Field(min_length=1, max_length=100)
    value: str = Field(max_length=100_000)
    source: AnswerSource = AnswerSource.USER
    confidence: float = Field(default=1, ge=0, le=1)


class ChallengeAnswerSuggestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    value: str = Field(max_length=100_000)
    source: AnswerSource
    provenance: dict[str, object] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)


class ChallengeModelRoute(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    tier: ChallengeModelTier
    task_type: AITaskType = AITaskType.ANSWER
    required_capabilities: set[AICapability]
    cache_allowed: bool
    escalation_reason: str | None = None


class ChallengeCompletionCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    review_fingerprint: str = Field(min_length=1, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=80)


class InterventionCompleteCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    prior_fingerprint: str = Field(min_length=1, max_length=200)


class ChallengeSessionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    workflow_id: str
    browser_session_id: str
    resume_state: WorkflowState
    detection: ChallengeDetection
    status: ChallengeStatus
    instructions: str
    questions: list[ChallengeQuestion]
    answers: list[ChallengeAnswer]
    current_position: int = Field(ge=0)
    flagged_question_ids: list[str]
    time_limit_seconds: int | None
    elapsed_seconds: int = Field(ge=0)
    remaining_seconds: int | None
    review_fingerprint: str | None = None
    completion_signal: str | None = None
    retry_count: int = Field(default=0, ge=0, le=20)
    created_at: datetime
    updated_at: datetime


class ChallengeEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    session_id: str
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=80)
    details: dict[str, object]
    occurred_at: datetime
