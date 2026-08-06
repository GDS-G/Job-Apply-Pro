from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from pydantic import AnyHttpUrl
from sqlalchemy.orm import Session

from job_apply_pro.browser.client import BrowserWorkerClient
from job_apply_pro.challenges.answer_mapping import ChallengeAnswerMapper
from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionKind,
    BrowserSessionCreate,
    BrowserVerification,
    LocatorStrategy,
    SemanticLocator,
    VerificationKind,
)
from job_apply_pro.domain.candidate import CandidateProfileCreate, ContactDetails
from job_apply_pro.domain.challenges import (
    ChallengeAnswerCommand,
    ChallengeCompletionCommand,
    ChallengeKind,
    ChallengeModelTier,
    ChallengeSessionCreate,
    ChallengeStatus,
    InterventionCompleteCommand,
)
from job_apply_pro.domain.workbench import MockWorkflowCreate
from job_apply_pro.domain.workflow import TransitionCommand, WorkflowState
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.browser_runtime import BrowserRuntimeService
from job_apply_pro.services.challenges import ChallengeService, ChallengeServiceError
from job_apply_pro.services.core import CoreService
from job_apply_pro.services.workbench import WorkbenchService
from job_apply_pro.storage.challenge_repository import ChallengeRepository
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    BrowserRuntimeRepository,
    CandidateRepository,
    CheckpointRepository,
    JobRepository,
    WorkbenchRepository,
)


class _ChallengeHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_GET(self) -> None:
        pages = {
            "/assessment": """
              <body data-page-type="ASSESSMENT">
                <h1>Automation assessment</h1><p>Time remaining 10:00</p>
                <label for="email">Email</label>
                <input id="email" data-canonical-field="email" required>
                <label for="response">Describe safe automation</label>
                <textarea id="response" required maxlength="200"></textarea>
                <label for="language">Preferred language</label>
                <select id="language" required>
                  <option value="">Choose</option><option value="Python">Python</option>
                  <option value="TypeScript">TypeScript</option>
                </select>
                <fieldset>
                  <legend>May we contact you?</legend>
                  <label><input name="contact" type="radio" value="yes" required> Yes</label>
                  <label><input name="contact" type="radio" value="no"> No</label>
                </fieldset>
                <label><input id="reviewed" type="checkbox" required> Instructions reviewed</label>
                <button type="button" onclick="location.href='/complete'">Submit assessment</button>
              </body>
            """,
            "/captcha": """
              <body data-page-type="CAPTCHA_CHALLENGE">
                <h1>reCAPTCHA interactive challenge</h1>
                <button type="button" onclick="location.href='/after'">
                  Human solved challenge
                </button>
              </body>
            """,
            "/after": "<body data-page-type='FORM'><h1>Application resumed</h1></body>",
            "/complete": """
              <body data-page-type="CHALLENGE_COMPLETE">
                <h1>Challenge complete</h1><p>Score recorded</p>
              </body>
            """,
        }
        body = pages.get(self.path)
        if body is None:
            self.send_error(404)
            return
        document = (
            f"<!doctype html><html><head><title>Challenge Fixture</title></head>{body}</html>"
        )
        payload = document.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@contextmanager
def _fixture() -> Generator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChallengeHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _workflow(session: Session, *, advance: bool) -> str:
    candidates = CandidateRepository(session)
    jobs = JobRepository(session)
    applications = ApplicationRepository(session)
    profile = CoreService(
        candidates,
        jobs,
        applications,
        CheckpointRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"c" * 32)),
    ).create_candidate(
        CandidateProfileCreate(
            display_name="Challenge profile",
            contact=ContactDetails(full_name="Challenge User", email="challenge@example.com"),
        )
    )
    workbench = WorkbenchRepository(session)
    workflow = WorkbenchService(candidates, jobs, applications, workbench).start_mock_workflow(
        MockWorkflowCreate(profile_id=profile.id, employer="Fixture", title="Engineer")
    )
    if advance:
        for target in (
            WorkflowState.SCORED,
            WorkflowState.ELIGIBILITY_CHECKED,
            WorkflowState.DOCUMENTS_SELECTED,
            WorkflowState.APPLICATION_OPENED,
            WorkflowState.FORM_MAPPED,
            WorkflowState.ANSWERS_VALIDATED,
        ):
            current = workbench.get_snapshot(workflow.workflow_id)
            assert current is not None
            workbench.apply_transition(
                workflow.workflow_id,
                TransitionCommand(
                    current_state=current.state,
                    next_state=target,
                    actor="fixture",
                    cause="Prepare challenge fixture",
                ),
            )
    return workflow.workflow_id


def _services(
    session: Session, tmp_path: Path, worker: BrowserWorkerClient
) -> tuple[BrowserRuntimeService, ChallengeService]:
    cipher = SensitiveDataCipher(StaticKeyProvider(b"c" * 32))
    workbench = WorkbenchRepository(session)
    browser = BrowserRuntimeService(
        BrowserRuntimeRepository(session),
        workbench,
        CheckpointRepository(session),
        cipher,
        worker,
        browser_data_dir=tmp_path / "browser",
        browser_artifact_dir=tmp_path / "artifacts",
        default_headless=True,
        automation_enabled=False,
    )
    return browser, ChallengeService(
        ChallengeRepository(session),
        workbench,
        browser,
        answer_mapper=ChallengeAnswerMapper(
            CandidateRepository(session), CandidateKnowledgeRepository(session), cipher
        ),
    )


def test_timed_assessment_answers_review_and_completion(session: Session, tmp_path: Path) -> None:
    worker = BrowserWorkerClient(timeout_seconds=75)
    try:
        workflow_id = _workflow(session, advance=True)
        browser, challenges = _services(session, tmp_path, worker)
        with _fixture() as origin:
            browser_session = browser.create_session(
                BrowserSessionCreate(
                    workflow_id=workflow_id,
                    start_url=AnyHttpUrl(f"{origin}/assessment"),
                    profile_name="assessment-fixture",
                )
            )
            challenge = challenges.detect(
                ChallengeSessionCreate(
                    workflow_id=workflow_id,
                    browser_session_id=browser_session.id,
                )
            )
            assert challenge.detection.kind is ChallengeKind.ASSESSMENT
            assert challenge.time_limit_seconds == 600
            assert len(challenge.questions) == 5
            suggestions = challenges.suggestions(challenge.id)
            assert [(item.value, item.source.value) for item in suggestions] == [
                ("challenge@example.com", "CANDIDATE_PROFILE")
            ]
            routes = {item.question_id: item for item in challenges.model_routes(challenge.id)}
            by_prompt = {question.prompt: question for question in challenge.questions}
            assert routes[by_prompt["Describe safe automation"].id].tier is (
                ChallengeModelTier.STRONG_REASONING
            )
            challenge = challenges.refresh(challenge.id)
            assert challenge.status is ChallengeStatus.IN_PROGRESS
            for prompt, value in (
                ("Email", "challenge@example.com"),
                ("Describe safe automation", "Verify every action."),
                ("Preferred language", "Python"),
                ("May we contact you?", "Yes"),
                ("Instructions reviewed", "true"),
            ):
                challenge = challenges.answer(
                    challenge.id,
                    ChallengeAnswerCommand(question_id=by_prompt[prompt].id, value=value),
                )
            assert challenge.status is ChallengeStatus.REVIEW_REQUIRED
            assert all(answer.verified for answer in challenge.answers)
            with pytest.raises(ChallengeServiceError, match="phrase"):
                challenges.complete(
                    challenge.id,
                    ChallengeCompletionCommand(
                        review_fingerprint=challenge.review_fingerprint or "missing",
                        confirmation_phrase="wrong",
                    ),
                )
            completed = challenges.complete(
                challenge.id,
                ChallengeCompletionCommand(
                    review_fingerprint=challenge.review_fingerprint or "missing",
                    confirmation_phrase="COMPLETE CHALLENGE",
                ),
            )
            assert completed.status is ChallengeStatus.COMPLETED
            assert completed.completion_signal == "Challenge complete"
            workflow = WorkbenchRepository(session).get_snapshot(workflow_id)
            assert workflow is not None
            assert workflow.state is WorkflowState.ASSESSMENT_COMPLETED
            assert [event.event_type for event in challenges.events(challenge.id)] == [
                "DETECTED",
                "RECOVERED",
                "ANSWER_VERIFIED",
                "ANSWER_VERIFIED",
                "ANSWER_VERIFIED",
                "ANSWER_VERIFIED",
                "ANSWER_VERIFIED",
                "COMPLETED",
            ]
            browser.stop(browser_session.id)
    finally:
        worker.close()


def test_captcha_requires_intervention_and_resumes_saved_state(
    session: Session, tmp_path: Path
) -> None:
    worker = BrowserWorkerClient(timeout_seconds=75)
    try:
        workflow_id = _workflow(session, advance=False)
        browser, challenges = _services(session, tmp_path, worker)
        with _fixture() as origin:
            browser_session = browser.create_session(
                BrowserSessionCreate(
                    workflow_id=workflow_id,
                    start_url=AnyHttpUrl(f"{origin}/captcha"),
                    profile_name="captcha-fixture",
                )
            )
            challenge = challenges.detect(
                ChallengeSessionCreate(
                    workflow_id=workflow_id,
                    browser_session_id=browser_session.id,
                )
            )
            assert challenge.status is ChallengeStatus.INTERVENTION_REQUIRED
            assert challenge.detection.provider == "reCAPTCHA"
            workflow = WorkbenchRepository(session).get_snapshot(workflow_id)
            assert workflow is not None and workflow.state is WorkflowState.CAPTCHA_REQUIRED
            result = browser.execute_action(
                browser_session.id,
                BrowserAction(
                    kind=BrowserActionKind.CLICK,
                    locator=SemanticLocator(
                        strategy=LocatorStrategy.ROLE,
                        value="button",
                        name="Human solved challenge",
                    ),
                    intended_result="Simulate completed user intervention",
                    verification=BrowserVerification(
                        kind=VerificationKind.URL_CONTAINS, value="/after"
                    ),
                ),
            )
            assert result.verified
            completed = challenges.intervention_complete(
                challenge.id,
                InterventionCompleteCommand(prior_fingerprint=challenge.detection.page_fingerprint),
            )
            assert completed.status is ChallengeStatus.COMPLETED
            workflow = WorkbenchRepository(session).get_snapshot(workflow_id)
            assert workflow is not None and workflow.state is WorkflowState.DEDUPLICATED
            browser.stop(browser_session.id)
    finally:
        worker.close()
