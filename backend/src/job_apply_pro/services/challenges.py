from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from job_apply_pro.challenges.answer_mapping import ChallengeAnswerMapper
from job_apply_pro.challenges.detection import ChallengeDetectionError, ChallengeDetector
from job_apply_pro.challenges.routing import ChallengeModelRoutingPolicy
from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionKind,
    BrowserPermission,
    BrowserVerification,
    ConfirmationState,
    LocatorStrategy,
    SemanticLocator,
    VerificationKind,
)
from job_apply_pro.domain.challenges import (
    ChallengeAnswer,
    ChallengeAnswerCommand,
    ChallengeAnswerSuggestion,
    ChallengeCompletionCommand,
    ChallengeEvent,
    ChallengeKind,
    ChallengeModelRoute,
    ChallengeQuestion,
    ChallengeSessionCreate,
    ChallengeSessionSnapshot,
    ChallengeStatus,
    InterventionCompleteCommand,
    QuestionKind,
)
from job_apply_pro.domain.workflow import (
    TransitionCommand,
    VerificationResult,
    WorkflowState,
    utc_now,
)
from job_apply_pro.services.browser_runtime import BrowserRuntimeService
from job_apply_pro.storage.repository_contracts import (
    ChallengeRepositoryProtocol,
    WorkbenchRepositoryProtocol,
)


class ChallengeServiceError(RuntimeError):
    pass


class ChallengeInterventionRequiredError(ChallengeServiceError):
    pass


class ChallengeService:
    def __init__(
        self,
        repository: ChallengeRepositoryProtocol,
        workbench: WorkbenchRepositoryProtocol,
        browser: BrowserRuntimeService,
        detector: ChallengeDetector | None = None,
        answer_mapper: ChallengeAnswerMapper | None = None,
        routing_policy: ChallengeModelRoutingPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._workbench = workbench
        self._browser = browser
        self._detector = detector or ChallengeDetector()
        self._answer_mapper = answer_mapper
        self._routing_policy = routing_policy or ChallengeModelRoutingPolicy()

    def detect(self, command: ChallengeSessionCreate) -> ChallengeSessionSnapshot:
        workflow = self._workbench.get_snapshot(command.workflow_id)
        if workflow is None:
            raise LookupError(f"Workflow {command.workflow_id} was not found")
        browser = self._browser.get_session(command.browser_session_id)
        if browser.workflow_id != command.workflow_id or browser.observation is None:
            raise ChallengeServiceError("Browser session does not belong to the workflow")
        observation = self._browser.observe(command.browser_session_id).observation
        if observation is None:
            raise ChallengeServiceError("Challenge page produced no observation")
        detection = self._detector.detect(observation)
        questions = (
            [] if detection.kind is ChallengeKind.CAPTCHA else self._detector.questions(observation)
        )
        visible_limit = self._detector.visible_timer_seconds(observation)
        time_limit = command.time_limit_seconds or visible_limit
        status = (
            ChallengeStatus.INTERVENTION_REQUIRED
            if detection.kind is ChallengeKind.CAPTCHA
            else ChallengeStatus.IN_PROGRESS
        )
        now = utc_now()
        snapshot = ChallengeSessionSnapshot(
            id=str(uuid4()),
            workflow_id=command.workflow_id,
            browser_session_id=command.browser_session_id,
            resume_state=workflow.state,
            detection=detection,
            status=status,
            instructions=observation.visible_text[:2_000],
            questions=questions,
            answers=[],
            current_position=0,
            flagged_question_ids=[],
            time_limit_seconds=time_limit,
            elapsed_seconds=0,
            remaining_seconds=time_limit,
            review_fingerprint=None,
            completion_signal=None,
            created_at=now,
            updated_at=now,
        )
        self._repository.save(snapshot)
        self._event(snapshot.id, "DETECTED", detection.model_dump(mode="json"))
        if detection.kind is ChallengeKind.CAPTCHA:
            self._transition(
                command.workflow_id,
                WorkflowState.CAPTCHA_REQUIRED,
                "CAPTCHA detected; browser state preserved for user intervention",
            )
        elif (
            detection.kind in {ChallengeKind.ASSESSMENT, ChallengeKind.QUIZ}
            and workflow.state is WorkflowState.ANSWERS_VALIDATED
        ):
            self._transition(
                command.workflow_id,
                WorkflowState.ASSESSMENT_PENDING,
                "Assessment instructions and questions were captured",
            )
            self._transition(
                command.workflow_id,
                WorkflowState.ASSESSMENT_IN_PROGRESS,
                "Timed assessment session started",
            )
        return snapshot

    def answer(self, session_id: str, command: ChallengeAnswerCommand) -> ChallengeSessionSnapshot:
        snapshot = self._active(session_id)
        snapshot = self._with_timer(snapshot)
        question = self._question(snapshot, command.question_id)
        if question.legal_attestation or question.signature_required:
            raise ChallengeInterventionRequiredError(
                "Legal attestations and signatures require direct user action"
            )
        value = command.value.strip()
        if question.required and not value:
            raise ChallengeServiceError("Required challenge answer is empty")
        if question.character_limit is not None and len(value) > question.character_limit:
            raise ChallengeServiceError("Challenge answer exceeds the character limit")
        if question.options and value not in question.options:
            raise ChallengeServiceError("Challenge answer is not an available option")
        result = self._browser.execute_action(
            snapshot.browser_session_id, self._answer_action(question, value)
        )
        if not result.verified:
            raise ChallengeServiceError(result.error or "Challenge answer was not verified")
        answer = ChallengeAnswer(
            question_id=question.id,
            value=value,
            source=command.source,
            provenance={"page_fingerprint": result.observation.page_fingerprint},
            confidence=command.confidence,
            verified=True,
            answered_at=utc_now(),
        )
        answers = [item for item in snapshot.answers if item.question_id != question.id] + [answer]
        required_ids = {item.id for item in snapshot.questions if item.required}
        answered_ids = {item.question_id for item in answers if item.verified and item.value}
        ready = required_ids <= answered_ids
        updated = snapshot.model_copy(
            update={
                "answers": answers,
                "current_position": question.position,
                "status": ChallengeStatus.REVIEW_REQUIRED if ready else ChallengeStatus.IN_PROGRESS,
                "review_fingerprint": result.observation.page_fingerprint if ready else None,
                "updated_at": utc_now(),
            }
        )
        self._repository.save(updated)
        self._event(
            session_id,
            "ANSWER_VERIFIED",
            {"question_id": question.id, "source": command.source.value},
        )
        return updated

    def complete(
        self, session_id: str, command: ChallengeCompletionCommand
    ) -> ChallengeSessionSnapshot:
        snapshot = self._with_timer(self.get(session_id))
        if snapshot.status is not ChallengeStatus.REVIEW_REQUIRED:
            raise ChallengeServiceError("Challenge is not ready for final review")
        if command.confirmation_phrase != "COMPLETE CHALLENGE":
            raise ChallengeServiceError("Challenge completion phrase did not match")
        if command.review_fingerprint != snapshot.review_fingerprint:
            raise ChallengeServiceError("Challenge review fingerprint did not match")
        current = self._browser.observe(snapshot.browser_session_id).observation
        if current is None or current.page_fingerprint != snapshot.review_fingerprint:
            raise ChallengeServiceError("Challenge page changed after review")
        button = (
            "Submit questionnaire"
            if snapshot.detection.kind is ChallengeKind.QUESTIONNAIRE
            else "Submit assessment"
        )
        result = self._browser.execute_action(
            snapshot.browser_session_id,
            BrowserAction(
                kind=BrowserActionKind.CLICK,
                locator=SemanticLocator(strategy=LocatorStrategy.ROLE, value="button", name=button),
                intended_result="Complete the reviewed challenge",
                verification=BrowserVerification(
                    kind=VerificationKind.TEXT_VISIBLE, value="Challenge complete"
                ),
                permission=BrowserPermission.ELEVATED,
                confirmation=ConfirmationState.CONFIRMED,
            ),
        )
        if not result.verified or result.observation.page_type != "CHALLENGE_COMPLETE":
            raise ChallengeServiceError("Challenge completion signal was not verified")
        if snapshot.detection.kind in {ChallengeKind.ASSESSMENT, ChallengeKind.QUIZ}:
            self._transition(
                snapshot.workflow_id,
                WorkflowState.ASSESSMENT_COMPLETED,
                "Assessment completion page was verified",
                verification=VerificationResult.PASSED,
            )
        updated = snapshot.model_copy(
            update={
                "status": ChallengeStatus.COMPLETED,
                "completion_signal": "Challenge complete",
                "updated_at": utc_now(),
            }
        )
        self._repository.save(updated)
        self._event(
            session_id, "COMPLETED", {"page_fingerprint": result.observation.page_fingerprint}
        )
        return updated

    def intervention_complete(
        self, session_id: str, command: InterventionCompleteCommand
    ) -> ChallengeSessionSnapshot:
        snapshot = self.get(session_id)
        if snapshot.status is not ChallengeStatus.INTERVENTION_REQUIRED:
            raise ChallengeServiceError("Challenge is not awaiting intervention")
        if command.prior_fingerprint != snapshot.detection.page_fingerprint:
            raise ChallengeServiceError("Intervention fingerprint did not match")
        observation = self._browser.observe(snapshot.browser_session_id).observation
        if observation is None:
            raise ChallengeServiceError("Browser observation is unavailable")
        try:
            detection = self._detector.detect(observation)
            if detection.kind is ChallengeKind.CAPTCHA:
                raise ChallengeInterventionRequiredError("CAPTCHA is still present")
        except ChallengeDetectionError:
            pass
        self._transition(
            snapshot.workflow_id,
            snapshot.resume_state,
            "User intervention cleared the CAPTCHA",
            verification=VerificationResult.PASSED,
        )
        updated = snapshot.model_copy(
            update={"status": ChallengeStatus.COMPLETED, "updated_at": utc_now()}
        )
        self._repository.save(updated)
        self._event(session_id, "INTERVENTION_COMPLETED", {})
        return updated

    def get(self, session_id: str) -> ChallengeSessionSnapshot:
        snapshot = self._repository.get(session_id)
        if snapshot is None:
            raise LookupError(f"Challenge session {session_id} was not found")
        return snapshot

    def list_sessions(self, workflow_id: str | None = None) -> list[ChallengeSessionSnapshot]:
        return self._repository.list_sessions(workflow_id)

    def events(self, session_id: str) -> list[ChallengeEvent]:
        self.get(session_id)
        return self._repository.list_events(session_id)

    def suggestions(self, session_id: str) -> list[ChallengeAnswerSuggestion]:
        snapshot = self.get(session_id)
        workflow = self._workbench.get_snapshot(snapshot.workflow_id)
        if workflow is None:
            raise LookupError(f"Workflow {snapshot.workflow_id} was not found")
        if self._answer_mapper is None:
            raise ChallengeServiceError("Challenge answer mapping is unavailable")
        return self._answer_mapper.suggest(snapshot, workflow.profile_id)

    def model_routes(self, session_id: str) -> list[ChallengeModelRoute]:
        snapshot = self.get(session_id)
        answers = {answer.question_id: answer for answer in snapshot.answers}
        return [
            self._routing_policy.route(
                question,
                instruction_length=len(snapshot.instructions),
                prior_confidence=(
                    answers[question.id].confidence if question.id in answers else None
                ),
            )
            for question in snapshot.questions
        ]

    def refresh(self, session_id: str) -> ChallengeSessionSnapshot:
        snapshot = self.get(session_id)
        observation = self._browser.observe(snapshot.browser_session_id).observation
        if observation is None:
            raise ChallengeServiceError("Browser observation is unavailable")
        try:
            detection = self._detector.detect(observation)
        except ChallengeDetectionError as error:
            raise ChallengeServiceError("Challenge page is no longer identifiable") from error
        if detection.kind is not snapshot.detection.kind:
            failed = snapshot.model_copy(
                update={"status": ChallengeStatus.FAILED, "updated_at": utc_now()}
            )
            self._repository.save(failed)
            self._event(
                session_id,
                "RECOVERY_FAILED",
                {"reason": "challenge_kind_changed", "observed_kind": detection.kind.value},
            )
            raise ChallengeServiceError("Challenge kind changed during recovery")
        prior_fingerprint = self._latest_verified_fingerprint(snapshot)
        changed = observation.page_fingerprint != prior_fingerprint
        answers = (
            [answer.model_copy(update={"verified": False}) for answer in snapshot.answers]
            if changed and snapshot.detection.kind is not ChallengeKind.CAPTCHA
            else snapshot.answers
        )
        status = snapshot.status
        review_fingerprint = snapshot.review_fingerprint
        if changed and status is ChallengeStatus.REVIEW_REQUIRED:
            status = ChallengeStatus.IN_PROGRESS
            review_fingerprint = None
        refreshed = self._with_timer(
            snapshot.model_copy(
                update={
                    "detection": detection,
                    "questions": (
                        snapshot.questions
                        if detection.kind is ChallengeKind.CAPTCHA
                        else self._detector.questions(observation)
                    ),
                    "answers": answers,
                    "status": status,
                    "review_fingerprint": review_fingerprint,
                    "updated_at": utc_now(),
                }
            )
        )
        self._repository.save(refreshed)
        self._event(
            session_id,
            "RECOVERED",
            {"page_changed": changed, "page_fingerprint": observation.page_fingerprint},
        )
        return refreshed

    def _active(self, session_id: str) -> ChallengeSessionSnapshot:
        snapshot = self.get(session_id)
        if snapshot.status not in {ChallengeStatus.IN_PROGRESS, ChallengeStatus.REVIEW_REQUIRED}:
            raise ChallengeServiceError(f"Challenge session is {snapshot.status}")
        return snapshot

    def _with_timer(self, snapshot: ChallengeSessionSnapshot) -> ChallengeSessionSnapshot:
        elapsed = max(0, int((datetime.now(UTC) - snapshot.created_at).total_seconds()))
        remaining = (
            max(0, snapshot.time_limit_seconds - elapsed)
            if snapshot.time_limit_seconds is not None
            else None
        )
        if remaining == 0:
            expired = snapshot.model_copy(
                update={
                    "elapsed_seconds": elapsed,
                    "remaining_seconds": 0,
                    "status": ChallengeStatus.EXPIRED,
                    "updated_at": utc_now(),
                }
            )
            self._repository.save(expired)
            self._event(snapshot.id, "EXPIRED", {})
            raise ChallengeServiceError("Challenge time limit expired")
        return snapshot.model_copy(
            update={"elapsed_seconds": elapsed, "remaining_seconds": remaining}
        )

    @staticmethod
    def _latest_verified_fingerprint(snapshot: ChallengeSessionSnapshot) -> str:
        latest = max(snapshot.answers, key=lambda answer: answer.answered_at, default=None)
        if latest is not None:
            fingerprint = latest.provenance.get("page_fingerprint")
            if isinstance(fingerprint, str):
                return fingerprint
        return snapshot.detection.page_fingerprint

    @staticmethod
    def _question(snapshot: ChallengeSessionSnapshot, question_id: str) -> ChallengeQuestion:
        for question in snapshot.questions:
            if question.id == question_id:
                return question
        raise LookupError(f"Challenge question {question_id} was not found")

    @staticmethod
    def _answer_action(question: ChallengeQuestion, value: str) -> BrowserAction:
        if question.kind is QuestionKind.MULTIPLE_CHOICE:
            locator = SemanticLocator(strategy=LocatorStrategy.LABEL, value=value)
            return BrowserAction(
                kind=BrowserActionKind.CHECK,
                locator=locator,
                intended_result=f"Select {value} for {question.prompt}",
                verification=BrowserVerification(
                    kind=VerificationKind.CHECKED_EQUALS,
                    value="true",
                    locator=locator,
                ),
            )
        locator = SemanticLocator(strategy=LocatorStrategy.LABEL, value=question.prompt)
        if question.kind in {QuestionKind.CHECKBOX, QuestionKind.TRUE_FALSE}:
            return BrowserAction(
                kind=BrowserActionKind.CHECK
                if value.casefold() not in {"false", "no", "0"}
                else BrowserActionKind.UNCHECK,
                locator=locator,
                intended_result=f"Set {question.prompt}",
                verification=BrowserVerification(
                    kind=VerificationKind.CHECKED_EQUALS,
                    value="false" if value.casefold() in {"false", "no", "0"} else "true",
                    locator=locator,
                ),
            )
        kind = (
            BrowserActionKind.SELECT
            if question.kind is QuestionKind.SELECT
            else BrowserActionKind.FILL
        )
        return BrowserAction(
            kind=kind,
            locator=locator,
            value=value,
            intended_result=f"Answer {question.prompt}",
            verification=BrowserVerification(
                kind=VerificationKind.VALUE_EQUALS, value=value, locator=locator
            ),
        )

    def _transition(
        self,
        workflow_id: str,
        target: WorkflowState,
        cause: str,
        *,
        verification: VerificationResult = VerificationResult.NOT_REQUIRED,
    ) -> None:
        current = self._workbench.get_snapshot(workflow_id)
        if current is None:
            raise LookupError(f"Workflow {workflow_id} was not found")
        self._workbench.apply_transition(
            workflow_id,
            TransitionCommand(
                current_state=current.state,
                next_state=target,
                actor="challenge-framework",
                cause=cause,
                verification=verification,
            ),
        )

    def _event(self, session_id: str, event_type: str, details: dict[str, object]) -> None:
        self._repository.add_event(
            ChallengeEvent(
                id=str(uuid4()),
                session_id=session_id,
                sequence=self._repository.next_event_sequence(session_id),
                event_type=event_type,
                details=details,
                occurred_at=utc_now(),
            )
        )
