from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import AnyHttpUrl
from sqlalchemy.orm import Session

from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionResult,
    BrowserEngine,
    BrowserObservation,
    BrowserSessionCreate,
    BrowserSessionSnapshot,
    BrowserSessionState,
    BrowserTab,
)
from job_apply_pro.domain.portals import (
    PortalInterventionReason,
    PortalKind,
    SupervisedPortalCapture,
    SupervisedPortalDisposition,
    SupervisedPortalRunCreate,
    SupervisedPortalRunState,
    SupervisedPortalSubmissionApproval,
)
from job_apply_pro.portals.catalog import PortalCatalog
from job_apply_pro.services.supervised_portals import (
    SupervisedPortalPolicyError,
    SupervisedPortalService,
    SupervisedPortalStateError,
    parse_portal_allowlist,
)
from job_apply_pro.storage.supervised_portal_repository import SupervisedPortalRepository


def _observation(
    *,
    page_type: str,
    fingerprint: str,
    visible_text: str,
    controls: list[dict[str, object]] | None = None,
) -> BrowserObservation:
    url = f"https://www.linkedin.com/jobs/{page_type.casefold()}"
    now = datetime.now(UTC)
    return BrowserObservation(
        sequence=1,
        url=url,
        title="LinkedIn fixture",
        origin="https://www.linkedin.com",
        page_type=page_type,
        page_fingerprint=fingerprint,
        tabs=[BrowserTab(index=0, url=url, title="LinkedIn fixture", active=True)],
        accessibility_snapshot="",
        visible_text=visible_text,
        controls=controls or [],
        validation_errors=[],
        modals=[],
        console_errors=[],
        network_failures=[],
        upload_status=[],
        download_status=[],
        screenshot_path=f"C:/fixture/{fingerprint}.png",
        observed_at=now,
    )


class _Browser:
    def __init__(
        self,
        initial: BrowserObservation,
        *,
        resume_observations: list[BrowserObservation] | None = None,
        action_observations: list[BrowserObservation] | None = None,
    ) -> None:
        self._observation = initial
        self._resume = list(resume_observations or [])
        self._actions = list(action_observations or [])
        self.state = BrowserSessionState.ACTIVE
        self.executed: list[BrowserAction] = []
        self.session_id = str(uuid4())

    def _snapshot(self, trace_path: str | None = None) -> BrowserSessionSnapshot:
        now = datetime.now(UTC)
        return BrowserSessionSnapshot(
            id=self.session_id,
            workflow_id="workflow-1",
            engine=BrowserEngine.CHROMIUM,
            profile_name="linkedin-fixture",
            state=self.state,
            current_url=self._observation.url,
            allowed_origins=["https://www.linkedin.com"],
            observation=self._observation,
            action_count=len(self.executed),
            trace_path=trace_path,
            created_at=now,
            updated_at=now,
        )

    def create_session(self, command: BrowserSessionCreate) -> BrowserSessionSnapshot:
        assert command.headless is False
        assert str(command.start_url).startswith("https://www.linkedin.com/")
        return self._snapshot()

    def resume(self, session_id: str) -> BrowserSessionSnapshot:
        assert session_id == self.session_id
        self.state = BrowserSessionState.ACTIVE
        if self._resume:
            self._observation = self._resume.pop(0)
        return self._snapshot()

    def takeover(self, session_id: str) -> BrowserSessionSnapshot:
        assert session_id == self.session_id
        self.state = BrowserSessionState.USER_TAKEOVER
        return self._snapshot()

    def execute_action(self, session_id: str, action: BrowserAction) -> BrowserActionResult:
        assert session_id == self.session_id
        self.executed.append(action)
        if self._actions:
            self._observation = self._actions.pop(0)
        return BrowserActionResult(
            id=str(uuid4()),
            session_id=session_id,
            sequence=len(self.executed),
            action=action,
            verified=True,
            attempts=1,
            observation=self._observation,
            created_at=datetime.now(UTC),
        )

    def stop(self, session_id: str) -> BrowserSessionSnapshot:
        assert session_id == self.session_id
        self.state = BrowserSessionState.STOPPED
        return self._snapshot(trace_path=str(Path("C:/fixture/trace.zip")))


def _service(
    session: Session,
    browser: _Browser,
    *,
    enabled: bool = True,
    submission_enabled: bool = True,
) -> SupervisedPortalService:
    return SupervisedPortalService(
        SupervisedPortalRepository(session),
        browser,
        PortalCatalog(),
        enabled=enabled,
        submission_enabled=submission_enabled,
        allowed_portals={PortalKind.LINKEDIN},
    )


def _start(service: SupervisedPortalService):  # type: ignore[no-untyped-def]
    return service.start(
        SupervisedPortalRunCreate(
            workflow_id="workflow-1",
            portal=PortalKind.LINKEDIN,
            start_url=AnyHttpUrl("https://www.linkedin.com/jobs/123"),
            profile_name="linkedin-fixture",
        )
    )


def test_supervised_run_captures_manual_steps_and_exact_final_submission(
    session: Session,
) -> None:
    detail = _observation(
        page_type="JOB_DETAIL",
        fingerprint="detail-fingerprint",
        visible_text="LinkedIn engineering role Apply",
    )
    review = _observation(
        page_type="SUBMISSION_REVIEW",
        fingerprint="review-fingerprint",
        visible_text="LinkedIn Review application",
        controls=[
            {
                "tag": "button",
                "type": "submit",
                "label": "Submit application",
                "disabled": False,
            }
        ],
    )
    confirmation = _observation(
        page_type="CONFIRMATION",
        fingerprint="confirmation-fingerprint",
        visible_text=("LinkedIn Application received. Confirmation number: LI-2048"),
    )
    browser = _Browser(
        detail,
        resume_observations=[review, review],
        action_observations=[confirmation],
    )
    service = _service(session, browser)

    started = _start(service)
    assert started.state is SupervisedPortalRunState.AWAITING_USER
    assert started.disposition is SupervisedPortalDisposition.USER_ACTION_REQUIRED
    assert started.intervention_reasons == [PortalInterventionReason.USER_TAKEOVER]
    assert len(started.evidence) == 1

    ready = service.capture(
        started.id,
        SupervisedPortalCapture(prior_page_fingerprint=started.page_fingerprint),
    )
    assert ready.state is SupervisedPortalRunState.READY_TO_SUBMIT
    assert ready.disposition is SupervisedPortalDisposition.FINAL_CONFIRMATION_REQUIRED
    assert len(ready.evidence) == 2

    with pytest.raises(SupervisedPortalStateError, match="fingerprint"):
        service.submit(
            ready.id,
            SupervisedPortalSubmissionApproval(
                review_fingerprint="stale",
                confirmation_phrase="SUBMIT APPLICATION",
            ),
        )

    completed = service.submit(
        ready.id,
        SupervisedPortalSubmissionApproval(
            review_fingerprint=ready.page_fingerprint,
            confirmation_phrase="SUBMIT APPLICATION",
        ),
    )
    assert completed.state is SupervisedPortalRunState.SUBMISSION_CONFIRMED
    assert completed.disposition is SupervisedPortalDisposition.CONFIRMATION_VERIFIED
    assert completed.trace_path == "C:\\fixture\\trace.zip"
    assert len(completed.evidence) == 3
    assert len(browser.executed) == 1
    action = browser.executed[0]
    assert action.locator is not None
    assert action.locator.name == "Submit application"
    assert action.confirmation.value == "CONFIRMED"
    assert action.permission.value == "ELEVATED"


def test_supervised_portal_requires_both_policy_gates_and_unambiguous_submit(
    session: Session,
) -> None:
    review = _observation(
        page_type="SUBMISSION_REVIEW",
        fingerprint="review-fingerprint",
        visible_text="LinkedIn Review application",
        controls=[
            {"tag": "button", "type": "submit", "text": "Submit application"},
            {"tag": "button", "type": "submit", "text": "Apply now"},
        ],
    )
    disabled = _service(session, _Browser(review), enabled=False)
    with pytest.raises(SupervisedPortalPolicyError, match="disabled"):
        _start(disabled)

    browser = _Browser(review, resume_observations=[review])
    service = _service(session, browser)
    ready = _start(service)
    assert ready.state is SupervisedPortalRunState.READY_TO_SUBMIT
    with pytest.raises(SupervisedPortalPolicyError, match="exactly one"):
        service.submit(
            ready.id,
            SupervisedPortalSubmissionApproval(
                review_fingerprint=ready.page_fingerprint,
                confirmation_phrase="SUBMIT APPLICATION",
            ),
        )

    no_submit = _service(
        session,
        _Browser(review),
        submission_enabled=False,
    )
    no_submit_run = _start(no_submit)
    with pytest.raises(SupervisedPortalPolicyError, match="disabled by local policy"):
        no_submit.submit(
            no_submit_run.id,
            SupervisedPortalSubmissionApproval(
                review_fingerprint=no_submit_run.page_fingerprint,
                confirmation_phrase="SUBMIT APPLICATION",
            ),
        )


def test_supervised_login_requires_manual_intervention_and_allowlist_is_strict(
    session: Session,
) -> None:
    login = _observation(
        page_type="LOGIN",
        fingerprint="login-fingerprint",
        visible_text="LinkedIn Sign in",
    )
    run = _start(_service(session, _Browser(login)))
    assert run.state is SupervisedPortalRunState.INTERVENTION_REQUIRED
    assert run.intervention_reasons == [PortalInterventionReason.LOGIN]
    assert parse_portal_allowlist("linkedin, workday") == {
        PortalKind.LINKEDIN,
        PortalKind.WORKDAY,
    }
    with pytest.raises(SupervisedPortalPolicyError, match="Unknown"):
        parse_portal_allowlist("not-a-portal")
    with pytest.raises(SupervisedPortalPolicyError, match="dedicated"):
        parse_portal_allowlist("reference_ats")
