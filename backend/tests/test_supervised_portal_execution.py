from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from pydantic import AnyHttpUrl, ValidationError
from sqlalchemy.orm import Session

from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionKind,
    BrowserActionResult,
    BrowserEngine,
    BrowserHeading,
    BrowserObservation,
    BrowserObservedControl,
    BrowserSessionCreate,
    BrowserSessionSnapshot,
    BrowserSessionState,
    BrowserTab,
)
from job_apply_pro.domain.greenhouse_form import GreenhouseFormAction
from job_apply_pro.domain.knowledge import CandidateDocumentVersionRecord
from job_apply_pro.domain.portals import (
    PortalInterventionReason,
    PortalKind,
    SupervisedPortalCapture,
    SupervisedPortalDisposition,
    SupervisedPortalLinkNavigationApproval,
    SupervisedPortalLinkNavigationReview,
    SupervisedPortalRunCreate,
    SupervisedPortalRunState,
    SupervisedPortalSubmissionApproval,
)
from job_apply_pro.portals.catalog import PortalCatalog
from job_apply_pro.services.browser_runtime import BrowserActionUncertainError
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
    headings: list[dict[str, object]] | None = None,
    url: str | None = None,
) -> BrowserObservation:
    page_url = url or f"https://www.linkedin.com/jobs/{page_type.casefold()}"
    parsed = urlsplit(page_url)
    now = datetime.now(UTC)
    return BrowserObservation(
        sequence=1,
        url=page_url,
        title="LinkedIn fixture",
        origin=f"{parsed.scheme}://{parsed.hostname}",
        page_type=page_type,
        page_fingerprint=fingerprint,
        headings=[BrowserHeading.model_validate(value) for value in headings or []],
        tabs=[BrowserTab(index=0, url=page_url, title="LinkedIn fixture", active=True)],
        accessibility_snapshot="",
        visible_text=visible_text,
        controls=[BrowserObservedControl.model_validate(value) for value in controls or []],
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
        observe_observations: list[BrowserObservation] | None = None,
        action_observations: list[BrowserObservation] | None = None,
        expected_start_prefix: str = "https://www.linkedin.com/",
        upload_dir: Path | None = None,
        upload_bytes: bytes = b"synthetic reviewed resume",
        action_error: Exception | None = None,
    ) -> None:
        self._observation = initial
        self._resume = list(resume_observations or [])
        self._observe = list(observe_observations or [])
        self._actions = list(action_observations or [])
        self.state = BrowserSessionState.ACTIVE
        self.executed: list[BrowserAction] = []
        self.session_id = str(uuid4())
        self.expected_start_prefix = expected_start_prefix
        self.upload_dir = upload_dir
        self.upload_bytes = upload_bytes
        self.action_error = action_error
        self.staged_paths: list[Path] = []
        self.clear_count = 0

    def _snapshot(self, trace_path: str | None = None) -> BrowserSessionSnapshot:
        now = datetime.now(UTC)
        return BrowserSessionSnapshot(
            id=self.session_id,
            workflow_id="workflow-1",
            engine=BrowserEngine.CHROMIUM,
            profile_name="linkedin-fixture",
            state=self.state,
            current_url=self._observation.url,
            allowed_origins=[self._observation.origin],
            observation=self._observation,
            action_count=len(self.executed),
            trace_path=trace_path,
            created_at=now,
            updated_at=now,
        )

    def create_session(self, command: BrowserSessionCreate) -> BrowserSessionSnapshot:
        assert command.headless is False
        assert str(command.start_url).startswith(self.expected_start_prefix)
        return self._snapshot()

    def get_session(self, session_id: str) -> BrowserSessionSnapshot:
        assert session_id == self.session_id
        return self._snapshot()

    def resume(self, session_id: str) -> BrowserSessionSnapshot:
        assert session_id == self.session_id
        self.state = BrowserSessionState.ACTIVE
        if self._resume:
            self._observation = self._resume.pop(0)
        return self._snapshot()

    def observe(self, session_id: str) -> BrowserSessionSnapshot:
        assert session_id == self.session_id
        if self._observe:
            self._observation = self._observe.pop(0)
        return self._snapshot()

    def takeover(self, session_id: str) -> BrowserSessionSnapshot:
        assert session_id == self.session_id
        self.state = BrowserSessionState.USER_TAKEOVER
        return self._snapshot()

    def execute_action(self, session_id: str, action: BrowserAction) -> BrowserActionResult:
        assert session_id == self.session_id
        self.executed.append(action)
        if self.action_error is not None:
            raise self.action_error
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

    def stage_encrypted_upload(
        self,
        session_id: str,
        *,
        version_id: str,
        encrypted_path: str,
        file_name: str,
        expected_sha256: str,
    ) -> str:
        assert session_id == self.session_id
        assert version_id == "version-1"
        assert encrypted_path == "C:/synthetic/encrypted.txt"
        assert hashlib.sha256(self.upload_bytes).hexdigest() == expected_sha256
        assert self.upload_dir is not None
        target = self.upload_dir / file_name
        target.write_bytes(self.upload_bytes)
        self.staged_paths.append(target)
        return str(target)

    def clear_staged_uploads(self, session_id: str) -> None:
        assert session_id == self.session_id
        self.clear_count += 1
        for path in self.staged_paths:
            path.unlink(missing_ok=True)

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
    allowed_portals: set[PortalKind] | None = None,
) -> SupervisedPortalService:
    return SupervisedPortalService(
        SupervisedPortalRepository(session),
        browser,
        PortalCatalog(),
        enabled=enabled,
        submission_enabled=submission_enabled,
        allowed_portals=allowed_portals or {PortalKind.LINKEDIN},
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


def _link_control(
    control_key: str,
    href: str,
    *,
    label: str = "View reviewed job",
    **updates: object,
) -> dict[str, object]:
    return {
        "index": 0,
        "control_key": control_key,
        "tag": "a",
        "label": label,
        "text": label,
        "href": href,
        "resolved_href": href,
        "visible": True,
        **updates,
    }


def test_reviewed_link_candidates_expose_only_plain_same_portal_targets(
    session: Session,
) -> None:
    source_url = "https://www.linkedin.com/jobs/search"
    source = _observation(
        page_type="JOB_SEARCH_RESULTS",
        fingerprint="link-search-v1",
        visible_text="LinkedIn jobs search results",
        url=source_url,
        controls=[
            _link_control("safe-link", "https://www.linkedin.com/jobs/view/456"),
            _link_control("query-link", "https://www.linkedin.com/jobs/view/456?trk=secret"),
            _link_control("fragment-link", "https://www.linkedin.com/jobs/view/456#apply"),
            _link_control(
                "download-link",
                "https://www.linkedin.com/jobs/export/456",
                href_download=True,
            ),
            _link_control("foreign-link", "https://example.invalid/jobs/456"),
            _link_control("current-link", source_url),
            _link_control("script-link", "javascript:submitApplication()"),
            _link_control(
                "credentialed-link",
                "https://fixture-user:fixture-secret@www.linkedin.com/jobs/view/456",
            ),
            _link_control("disabled-link", "https://www.linkedin.com/jobs/view/789", disabled=True),
            _link_control("duplicate-link", "https://www.linkedin.com/jobs/view/111"),
            _link_control("duplicate-link", "https://www.linkedin.com/jobs/view/222"),
        ],
    )
    service = _service(session, _Browser(source))

    run = _start(service)

    assert [candidate.control_key for candidate in run.reviewed_links] == ["safe-link"]
    assert run.reviewed_links[0].label == "View reviewed job"
    assert run.reviewed_links[0].target_origin == "https://www.linkedin.com"
    assert run.reviewed_links[0].target_path == "/jobs/view/456"
    assert source.controls[1].href == "https://www.linkedin.com/jobs/view/456"
    assert source.controls[1].href_has_query
    assert source.controls[2].href_has_fragment
    credentialed = next(
        control for control in source.controls if control.control_key == "credentialed-link"
    )
    assert credentialed.href_has_credentials
    assert "fixture-user" not in credentialed.model_dump_json()
    assert "fixture-secret" not in credentialed.model_dump_json()


def test_native_reviewed_link_navigation_composes_exact_url_action(
    session: Session,
) -> None:
    source = _observation(
        page_type="JOB_SEARCH_RESULTS",
        fingerprint="link-search-v1",
        visible_text="LinkedIn jobs search results",
        url="https://www.linkedin.com/jobs/search",
        controls=[_link_control("safe-link", "https://www.linkedin.com/jobs/view/456")],
    )
    target = _observation(
        page_type="JOB_DETAIL",
        fingerprint="link-detail-v2",
        visible_text="LinkedIn engineering role Apply",
        url="https://www.linkedin.com/jobs/view/456",
    )
    browser = _Browser(source, action_observations=[target])
    service = _service(session, browser)
    run = _start(service)

    preview = service.preview_reviewed_link_navigation(
        run.id,
        "safe-link",
        SupervisedPortalLinkNavigationReview(expected_page_fingerprint=run.page_fingerprint),
    )
    assert preview.run_id == run.id
    assert preview.browser_session_id == run.browser_session_id
    assert preview.target_origin == "https://www.linkedin.com"
    assert preview.target_path == "/jobs/view/456"
    assert len(preview.review_fingerprint) == 64

    updated = service.navigate_reviewed_link(
        run.id,
        "safe-link",
        SupervisedPortalLinkNavigationApproval(
            expected_review_fingerprint=preview.review_fingerprint,
            confirmation_phrase="NAVIGATE REVIEWED LINK",
        ),
    )

    assert len(browser.executed) == 1
    action = browser.executed[0]
    assert action.kind is BrowserActionKind.NAVIGATE
    assert str(action.url) == "https://www.linkedin.com/jobs/view/456"
    assert action.locator is None
    assert action.preconditions == []
    assert action.verification.kind.value == "URL_EQUALS"
    assert action.verification.value == str(action.url)
    assert action.permission.value == "STANDARD"
    assert action.confirmation.value == "NOT_REQUIRED"
    assert updated.current_url == str(action.url)
    assert updated.page_fingerprint == target.page_fingerprint
    assert updated.evidence[-1].action_kind is BrowserActionKind.NAVIGATE
    assert updated.evidence[-1].verified
    assert browser.state is BrowserSessionState.USER_TAKEOVER


def test_linkedin_job_identity_is_read_only_and_bound_to_exact_captured_page(
    session: Session,
) -> None:
    detail = _observation(
        page_type="JOB_DETAIL",
        fingerprint="linkedin-detail-v2",
        visible_text="LinkedIn Senior Platform Engineer Apply",
        url="https://www.linkedin.com/jobs/view/456",
        headings=[{"level": 1, "text": "  Senior   Platform Engineer  "}],
    )
    browser = _Browser(detail)
    service = _service(session, browser)
    run = _start(service)

    review = service.review_linkedin_job_identity(run.id)

    assert review.run_id == run.id
    assert review.browser_session_id == run.browser_session_id
    assert str(review.source_url) == "https://www.linkedin.com/jobs/view/456"
    assert review.external_id == "456"
    assert review.title == "Senior Platform Engineer"
    assert review.page_fingerprint == run.page_fingerprint
    assert len(review.review_fingerprint) == 64
    assert review.notice.startswith("Read-only identity review")
    assert browser.executed == []
    assert browser.state is BrowserSessionState.USER_TAKEOVER


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/456?tracking=blocked",
        "https://www.linkedin.com/jobs/view/456#apply",
        "https://www.linkedin.com/jobs/view/0456",
        "https://www.linkedin.com/jobs/search/456",
    ],
)
def test_linkedin_job_identity_rejects_noncanonical_urls(session: Session, url: str) -> None:
    detail = _observation(
        page_type="JOB_DETAIL",
        fingerprint="linkedin-detail-v2",
        visible_text="LinkedIn Senior Platform Engineer Apply",
        url=url,
        headings=[{"level": 1, "text": "Senior Platform Engineer"}],
    )
    service = _service(session, _Browser(detail))
    run = _start(service)

    with pytest.raises(SupervisedPortalPolicyError, match="plain canonical"):
        service.review_linkedin_job_identity(run.id)


@pytest.mark.parametrize(
    "headings",
    [
        [],
        [{"level": 2, "text": "Senior Platform Engineer"}],
        [
            {"level": 1, "text": "Senior Platform Engineer"},
            {"level": 1, "text": "Unexpected duplicate"},
        ],
    ],
)
def test_linkedin_job_identity_requires_one_visible_h1(
    session: Session, headings: list[dict[str, object]]
) -> None:
    detail = _observation(
        page_type="JOB_DETAIL",
        fingerprint="linkedin-detail-v2",
        visible_text="LinkedIn Senior Platform Engineer Apply",
        url="https://www.linkedin.com/jobs/view/456",
        headings=headings,
    )
    service = _service(session, _Browser(detail))
    run = _start(service)

    with pytest.raises(SupervisedPortalPolicyError, match="exactly one visible"):
        service.review_linkedin_job_identity(run.id)


def test_linkedin_job_identity_rejects_a_page_changed_after_capture(
    session: Session,
) -> None:
    detail = _observation(
        page_type="JOB_DETAIL",
        fingerprint="linkedin-detail-v2",
        visible_text="LinkedIn Senior Platform Engineer Apply",
        url="https://www.linkedin.com/jobs/view/456",
        headings=[{"level": 1, "text": "Senior Platform Engineer"}],
    )
    changed = detail.model_copy(update={"page_fingerprint": "linkedin-detail-v3"})
    service = _service(session, _Browser(detail, observe_observations=[changed]))
    run = _start(service)

    with pytest.raises(SupervisedPortalStateError, match="page changed"):
        service.review_linkedin_job_identity(run.id)


def test_linkedin_job_identity_requires_user_takeover(
    session: Session,
) -> None:
    detail = _observation(
        page_type="JOB_DETAIL",
        fingerprint="linkedin-detail-v2",
        visible_text="LinkedIn Senior Platform Engineer Apply",
        url="https://www.linkedin.com/jobs/view/456",
        headings=[{"level": 1, "text": "Senior Platform Engineer"}],
    )
    browser = _Browser(detail)
    service = _service(session, browser)
    run = _start(service)
    browser.state = BrowserSessionState.ACTIVE

    with pytest.raises(SupervisedPortalStateError, match="user-takeover session"):
        service.review_linkedin_job_identity(run.id)


def test_linkedin_job_identity_rejects_other_portal_authority(
    session: Session,
) -> None:
    detail = _observation(
        page_type="JOB_DETAIL",
        fingerprint="indeed-detail-v1",
        visible_text="Indeed Senior Platform Engineer Apply",
        url="https://www.indeed.com/jobs/view/456",
        headings=[{"level": 1, "text": "Senior Platform Engineer"}],
    )
    browser = _Browser(detail, expected_start_prefix="https://www.indeed.com/")
    service = _service(
        session,
        browser,
        allowed_portals={PortalKind.LINKEDIN, PortalKind.INDEED},
    )
    run = service.start(
        SupervisedPortalRunCreate(
            workflow_id="workflow-1",
            portal=PortalKind.INDEED,
            start_url=AnyHttpUrl("https://www.indeed.com/jobs/view/456"),
            profile_name="indeed-fixture",
        )
    )

    with pytest.raises(SupervisedPortalPolicyError, match="LINKEDIN runs only"):
        service.review_linkedin_job_identity(run.id)


def test_reviewed_link_navigation_reproves_page_and_rejects_injected_authority(
    session: Session,
) -> None:
    source = _observation(
        page_type="JOB_SEARCH_RESULTS",
        fingerprint="link-search-v1",
        visible_text="LinkedIn jobs search results",
        url="https://www.linkedin.com/jobs/search",
        controls=[_link_control("safe-link", "https://www.linkedin.com/jobs/view/456")],
    )
    changed = source.model_copy(update={"page_fingerprint": "link-search-changed", "controls": []})
    browser = _Browser(source, observe_observations=[source, changed])
    service = _service(session, browser)
    run = _start(service)
    preview = service.preview_reviewed_link_navigation(
        run.id,
        "safe-link",
        SupervisedPortalLinkNavigationReview(expected_page_fingerprint=run.page_fingerprint),
    )

    with pytest.raises(SupervisedPortalStateError, match="page changed"):
        service.navigate_reviewed_link(
            run.id,
            "safe-link",
            SupervisedPortalLinkNavigationApproval(
                expected_review_fingerprint=preview.review_fingerprint,
                confirmation_phrase="NAVIGATE REVIEWED LINK",
            ),
        )
    assert browser.executed == []
    assert browser.state is BrowserSessionState.USER_TAKEOVER

    with pytest.raises(ValidationError, match="extra_forbidden"):
        SupervisedPortalLinkNavigationApproval.model_validate(
            {
                "expected_review_fingerprint": preview.review_fingerprint,
                "confirmation_phrase": "NAVIGATE REVIEWED LINK",
                "url": "https://untrusted.invalid",
            }
        )


def test_reviewed_link_navigation_never_retries_an_uncertain_external_effect(
    session: Session,
) -> None:
    source = _observation(
        page_type="JOB_SEARCH_RESULTS",
        fingerprint="link-search-v1",
        visible_text="LinkedIn jobs search results",
        url="https://www.linkedin.com/jobs/search",
        controls=[_link_control("safe-link", "https://www.linkedin.com/jobs/view/456")],
    )
    browser = _Browser(
        source,
        action_error=BrowserActionUncertainError(
            "Browser action outcome is uncertain; automatic retry is blocked"
        ),
    )
    service = _service(session, browser)
    run = _start(service)
    preview = service.preview_reviewed_link_navigation(
        run.id,
        "safe-link",
        SupervisedPortalLinkNavigationReview(expected_page_fingerprint=run.page_fingerprint),
    )

    with pytest.raises(BrowserActionUncertainError, match="automatic retry is blocked"):
        service.navigate_reviewed_link(
            run.id,
            "safe-link",
            SupervisedPortalLinkNavigationApproval(
                expected_review_fingerprint=preview.review_fingerprint,
                confirmation_phrase="NAVIGATE REVIEWED LINK",
            ),
        )

    assert len(browser.executed) == 1
    assert browser.executed[0].kind is BrowserActionKind.NAVIGATE
    assert browser.state is BrowserSessionState.USER_TAKEOVER


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
    assert started.observed_controls == []

    ready = service.capture(
        started.id,
        SupervisedPortalCapture(prior_page_fingerprint=started.page_fingerprint),
    )
    assert ready.state is SupervisedPortalRunState.READY_TO_SUBMIT
    assert ready.disposition is SupervisedPortalDisposition.FINAL_CONFIRMATION_REQUIRED
    assert len(ready.evidence) == 2
    assert ready.observed_controls[0].kind.value == "BUTTON"
    assert ready.observed_controls[0].label == "Submit application"

    with pytest.raises(SupervisedPortalStateError, match="fingerprint"):
        service.submit(
            ready.id,
            SupervisedPortalSubmissionApproval(
                review_fingerprint="stale",
                confirmation_phrase="SUBMIT APPLICATION",
            ),
        )
    with pytest.raises(SupervisedPortalPolicyError, match="another portal"):
        service.submit(
            ready.id,
            SupervisedPortalSubmissionApproval(
                review_fingerprint=ready.page_fingerprint,
                greenhouse_form_review_fingerprint="a" * 64,
                confirmation_phrase="SUBMIT APPLICATION",
            ),
        )
    assert browser.executed == []

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


def test_greenhouse_cannot_start_through_the_generic_supervised_boundary(
    session: Session,
) -> None:
    observation = _observation(
        page_type="JOB_DETAIL",
        fingerprint="greenhouse-detail",
        visible_text="Synthetic Greenhouse role",
    )
    service = SupervisedPortalService(
        SupervisedPortalRepository(session),
        _Browser(observation),
        PortalCatalog(),
        enabled=True,
        submission_enabled=False,
        allowed_portals={PortalKind.GREENHOUSE},
    )
    command = SupervisedPortalRunCreate(
        workflow_id="workflow-1",
        portal=PortalKind.GREENHOUSE,
        start_url=AnyHttpUrl("https://boards.greenhouse.io/example/jobs/1"),
        profile_name="greenhouse-fixture",
    )
    with pytest.raises(SupervisedPortalPolicyError, match="reviewed Greenhouse"):
        service.start(command)


def test_reviewed_greenhouse_start_persists_launch_fingerprint_as_first_evidence(
    session: Session,
) -> None:
    launch_fingerprint = "a" * 64
    observation = _observation(
        page_type="JOB_DETAIL",
        fingerprint="greenhouse-detail",
        visible_text="Greenhouse engineering role Apply",
        url="https://boards.greenhouse.io/example/jobs/1",
    )
    service = SupervisedPortalService(
        SupervisedPortalRepository(session),
        _Browser(observation, expected_start_prefix="https://boards.greenhouse.io/"),
        PortalCatalog(),
        enabled=True,
        submission_enabled=False,
        allowed_portals={PortalKind.GREENHOUSE},
    )
    run = service.start_reviewed_greenhouse(
        SupervisedPortalRunCreate(
            workflow_id="workflow-1",
            portal=PortalKind.GREENHOUSE,
            start_url=AnyHttpUrl("https://boards.greenhouse.io/example/jobs/1"),
            profile_name="greenhouse-fixture",
        ),
        launch_fingerprint,
    )
    assert run.evidence[0].before_fingerprint == launch_fingerprint
    assert run.evidence[0].after_fingerprint == observation.page_fingerprint
    assert len(run.evidence[0].action_fingerprint) == 64


def test_reviewed_greenhouse_capture_exposes_current_form_contract(
    session: Session,
) -> None:
    detail = _observation(
        page_type="JOB_DETAIL",
        fingerprint="greenhouse-detail",
        visible_text="Greenhouse engineering role Apply",
        url="https://boards.greenhouse.io/example/jobs/1",
    )
    form = _observation(
        page_type="APPLICATION_FORM",
        fingerprint="greenhouse-contact-form",
        visible_text="Greenhouse application Submit",
        url="https://boards.greenhouse.io/example/jobs/1#app",
        controls=[
            {
                "index": 0,
                "control_key": "email",
                "tag": "input",
                "type": "email",
                "label": "Email",
                "label_source": "LABEL",
                "required": True,
                "visible": True,
                "will_validate": True,
                "constraint_satisfied": False,
            },
            {
                "index": 1,
                "control_key": "next",
                "tag": "button",
                "text": "Next",
                "visible": True,
            },
        ],
    )
    service = SupervisedPortalService(
        SupervisedPortalRepository(session),
        _Browser(
            detail,
            resume_observations=[form],
            expected_start_prefix="https://boards.greenhouse.io/",
        ),
        PortalCatalog(),
        enabled=True,
        submission_enabled=False,
        allowed_portals={PortalKind.GREENHOUSE},
    )
    started = service.start_reviewed_greenhouse(
        SupervisedPortalRunCreate(
            workflow_id="workflow-1",
            portal=PortalKind.GREENHOUSE,
            start_url=AnyHttpUrl("https://boards.greenhouse.io/example/jobs/1"),
            profile_name="greenhouse-fixture",
        ),
        "b" * 64,
    )
    assert started.greenhouse_form is None

    captured = service.capture(
        started.id,
        SupervisedPortalCapture(prior_page_fingerprint=started.page_fingerprint),
    )
    assert captured.greenhouse_form is not None
    assert captured.greenhouse_form.page_fingerprint == captured.page_fingerprint
    assert captured.greenhouse_form.review_field_count == 1
    assert captured.greenhouse_form.navigation_control_key == "next"
    assert not captured.greenhouse_form.ready_to_advance


def test_reviewed_greenhouse_submission_requires_current_contract_and_identifier(
    session: Session,
) -> None:
    review = _observation(
        page_type="SUBMISSION_REVIEW",
        fingerprint="greenhouse-review",
        visible_text="Greenhouse review application Submit application",
        url="https://boards.greenhouse.io/example/jobs/1#review",
        controls=[
            {
                "index": 0,
                "control_key": "submit",
                "tag": "button",
                "type": "submit",
                "text": "Submit application",
                "visible": True,
            }
        ],
    )
    confirmation = _observation(
        page_type="CONFIRMATION",
        fingerprint="greenhouse-confirmation",
        visible_text="Greenhouse application received confirmation: GH-TEST-1",
        url="https://boards.greenhouse.io/example/jobs/1/confirmation",
    )
    browser = _Browser(
        review,
        action_observations=[confirmation],
        expected_start_prefix="https://boards.greenhouse.io/",
    )
    service = SupervisedPortalService(
        SupervisedPortalRepository(session),
        browser,
        PortalCatalog(),
        enabled=True,
        submission_enabled=True,
        allowed_portals={PortalKind.GREENHOUSE},
    )
    run = service.start_reviewed_greenhouse(
        SupervisedPortalRunCreate(
            workflow_id="workflow-1",
            portal=PortalKind.GREENHOUSE,
            start_url=AnyHttpUrl(str(review.url)),
            profile_name="greenhouse-fixture",
        ),
        "f" * 64,
    )
    assert run.state is SupervisedPortalRunState.READY_TO_SUBMIT
    assert run.greenhouse_form is not None
    assert run.greenhouse_form.controls[0].action is GreenhouseFormAction.FINAL_SUBMISSION_GATE

    with pytest.raises(SupervisedPortalPolicyError, match="current form review"):
        service.submit(
            run.id,
            SupervisedPortalSubmissionApproval(
                review_fingerprint=run.page_fingerprint,
                confirmation_phrase="SUBMIT APPLICATION",
            ),
        )
    with pytest.raises(SupervisedPortalStateError, match="form review changed"):
        service.submit(
            run.id,
            SupervisedPortalSubmissionApproval(
                review_fingerprint=run.page_fingerprint,
                greenhouse_form_review_fingerprint="0" * 64,
                confirmation_phrase="SUBMIT APPLICATION",
            ),
        )
    assert browser.executed == []

    completed = service.submit(
        run.id,
        SupervisedPortalSubmissionApproval(
            review_fingerprint=run.page_fingerprint,
            greenhouse_form_review_fingerprint=run.greenhouse_form.review_fingerprint,
            confirmation_phrase="SUBMIT APPLICATION",
        ),
    )
    assert completed.state is SupervisedPortalRunState.SUBMISSION_CONFIRMED
    assert completed.disposition is SupervisedPortalDisposition.CONFIRMATION_VERIFIED
    assert completed.evidence[-1].verified
    assert len(browser.executed) == 1
    assert browser.executed[0].locator == review.controls[0].locator
    assert browser.executed[0].preconditions[0].kind.value == "LOCATOR_VISIBLE"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        SupervisedPortalSubmissionApproval.model_validate(
            {
                "review_fingerprint": run.page_fingerprint,
                "greenhouse_form_review_fingerprint": "a" * 64,
                "confirmation_phrase": "SUBMIT APPLICATION",
                "url": "https://untrusted.invalid",
            }
        )


def test_reviewed_greenhouse_submission_rejects_ambiguous_contract(
    session: Session,
) -> None:
    review = _observation(
        page_type="SUBMISSION_REVIEW",
        fingerprint="greenhouse-ambiguous-review",
        visible_text="Greenhouse review application Submit application",
        url="https://boards.greenhouse.io/example/jobs/1#review",
        controls=[
            {
                "index": index,
                "control_key": f"submit-{index}",
                "tag": "button",
                "type": "submit",
                "text": "Submit application",
                "visible": True,
            }
            for index in range(2)
        ],
    )
    browser = _Browser(review, expected_start_prefix="https://boards.greenhouse.io/")
    service = SupervisedPortalService(
        SupervisedPortalRepository(session),
        browser,
        PortalCatalog(),
        enabled=True,
        submission_enabled=True,
        allowed_portals={PortalKind.GREENHOUSE},
    )
    run = service.start_reviewed_greenhouse(
        SupervisedPortalRunCreate(
            workflow_id="workflow-1",
            portal=PortalKind.GREENHOUSE,
            start_url=AnyHttpUrl(str(review.url)),
            profile_name="greenhouse-fixture",
        ),
        "1" * 64,
    )
    assert run.greenhouse_form is not None
    with pytest.raises(SupervisedPortalPolicyError, match="exactly one"):
        service.submit(
            run.id,
            SupervisedPortalSubmissionApproval(
                review_fingerprint=run.page_fingerprint,
                greenhouse_form_review_fingerprint=run.greenhouse_form.review_fingerprint,
                confirmation_phrase="SUBMIT APPLICATION",
            ),
        )
    assert browser.executed == []


@pytest.mark.parametrize(
    ("confirmation_url", "confirmation_text"),
    [
        (
            "https://boards.greenhouse.io/example/jobs/1/confirmation",
            "Greenhouse application received",
        ),
        (
            "https://job-boards.greenhouse.io/example/jobs/1/confirmation",
            "Greenhouse application received confirmation: GH-FOREIGN-1",
        ),
    ],
    ids=["identifier-missing", "origin-changed"],
)
def test_reviewed_greenhouse_submission_preserves_uncertainty_after_click(
    session: Session,
    confirmation_url: str,
    confirmation_text: str,
) -> None:
    review = _observation(
        page_type="SUBMISSION_REVIEW",
        fingerprint="greenhouse-uncertain-review",
        visible_text="Greenhouse review application Submit application",
        url="https://boards.greenhouse.io/example/jobs/1#review",
        controls=[
            {
                "index": 0,
                "control_key": "submit",
                "tag": "button",
                "type": "submit",
                "text": "Submit application",
                "visible": True,
            }
        ],
    )
    confirmation = _observation(
        page_type="CONFIRMATION",
        fingerprint="greenhouse-uncertain-confirmation",
        visible_text=confirmation_text,
        url=confirmation_url,
    )
    browser = _Browser(
        review,
        action_observations=[confirmation],
        expected_start_prefix="https://boards.greenhouse.io/",
    )
    service = SupervisedPortalService(
        SupervisedPortalRepository(session),
        browser,
        PortalCatalog(),
        enabled=True,
        submission_enabled=True,
        allowed_portals={PortalKind.GREENHOUSE},
    )
    run = service.start_reviewed_greenhouse(
        SupervisedPortalRunCreate(
            workflow_id="workflow-1",
            portal=PortalKind.GREENHOUSE,
            start_url=AnyHttpUrl(str(review.url)),
            profile_name="greenhouse-fixture",
        ),
        "2" * 64,
    )
    assert run.greenhouse_form is not None

    uncertain = service.submit(
        run.id,
        SupervisedPortalSubmissionApproval(
            review_fingerprint=run.page_fingerprint,
            greenhouse_form_review_fingerprint=run.greenhouse_form.review_fingerprint,
            confirmation_phrase="SUBMIT APPLICATION",
        ),
    )

    assert uncertain.state is SupervisedPortalRunState.SUBMISSION_UNCERTAIN
    assert uncertain.disposition is SupervisedPortalDisposition.CONFIRMATION_UNCERTAIN
    assert uncertain.intervention_reasons == [PortalInterventionReason.USER_TAKEOVER]
    assert not uncertain.evidence[-1].verified
    assert browser.state is BrowserSessionState.USER_TAKEOVER
    assert len(browser.executed) == 1
    with pytest.raises(SupervisedPortalStateError, match="not ready"):
        service.submit(
            run.id,
            SupervisedPortalSubmissionApproval(
                review_fingerprint=uncertain.page_fingerprint,
                greenhouse_form_review_fingerprint=(
                    uncertain.greenhouse_form.review_fingerprint
                    if uncertain.greenhouse_form is not None
                    else "0" * 64
                ),
                confirmation_phrase="SUBMIT APPLICATION",
            ),
        )
    assert len(browser.executed) == 1


def test_reviewed_greenhouse_upload_uses_exact_document_and_postcondition(
    session: Session, tmp_path: Path
) -> None:
    pending = _observation(
        page_type="DOCUMENT_UPLOAD",
        fingerprint="greenhouse-document-pending",
        visible_text="Greenhouse document upload",
        url="https://boards.greenhouse.io/example/jobs/1#documents",
        controls=[
            {
                "index": 0,
                "control_key": "resume",
                "tag": "input",
                "type": "file",
                "label": "Resume",
                "label_source": "LABEL",
                "required": True,
                "native_required": True,
                "visible": True,
                "will_validate": True,
                "constraint_satisfied": False,
                "locator": {
                    "strategy": "LABEL",
                    "value": "Resume",
                    "exact": True,
                },
            }
        ],
    )
    ready = pending.model_copy(
        update={
            "sequence": 2,
            "page_fingerprint": "greenhouse-document-ready",
            "upload_status": ["candidate-resume.pdf"],
            "controls": [pending.controls[0].model_copy(update={"constraint_satisfied": True})],
        }
    )
    browser = _Browser(
        pending,
        action_observations=[ready],
        expected_start_prefix="https://boards.greenhouse.io/",
        upload_dir=tmp_path,
    )
    service = SupervisedPortalService(
        SupervisedPortalRepository(session),
        browser,
        PortalCatalog(),
        enabled=True,
        submission_enabled=False,
        allowed_portals={PortalKind.GREENHOUSE},
    )
    run = service.start_reviewed_greenhouse(
        SupervisedPortalRunCreate(
            workflow_id="workflow-1",
            portal=PortalKind.GREENHOUSE,
            start_url=AnyHttpUrl(str(pending.url)),
            profile_name="greenhouse-fixture",
        ),
        "c" * 64,
    )
    assert run.greenhouse_form is not None
    assessment = run.greenhouse_form
    assert assessment.controls[0].action is GreenhouseFormAction.REVIEW_DOCUMENT_UPLOAD
    document = CandidateDocumentVersionRecord(
        id="version-1",
        document_id="document-1",
        version=1,
        file_name="candidate-resume.pdf",
        media_type="application/pdf",
        sha256=hashlib.sha256(browser.upload_bytes).hexdigest(),
        parser_version="synthetic-v1",
        page_count=1,
        character_count=32,
        created_at=datetime.now(UTC),
        storage_path="C:/synthetic/encrypted.txt",
        encrypted_extraction="synthetic",
    )

    completed = service.upload_reviewed_greenhouse_document(
        run.id,
        form_review_fingerprint=assessment.review_fingerprint,
        control_key="resume",
        document=document,
    )

    assert completed.page_fingerprint == ready.page_fingerprint
    assert completed.greenhouse_form is not None
    assert completed.greenhouse_form.satisfied_required_count == 1
    assert completed.evidence[-1].verified
    assert completed.evidence[-1].action_kind is BrowserActionKind.UPLOAD
    assert browser.executed[0].permission.value == "ELEVATED"
    assert browser.executed[0].confirmation.value == "CONFIRMED"
    assert browser.executed[0].preconditions[0].kind.value == "LOCATOR_VISIBLE"
    assert browser.clear_count == 1
    assert not browser.staged_paths[0].exists()
    assert browser.state is BrowserSessionState.USER_TAKEOVER


def test_reviewed_greenhouse_navigation_requires_fresh_ready_page_and_later_stage(
    session: Session,
) -> None:
    application = _observation(
        page_type="APPLICATION_FORM",
        fingerprint="greenhouse-application-ready",
        visible_text="Greenhouse application",
        url="https://boards.greenhouse.io/example/jobs/1#application",
        controls=[
            {
                "index": 0,
                "control_key": "email",
                "tag": "input",
                "type": "email",
                "label": "Email",
                "label_source": "LABEL",
                "required": True,
                "native_required": True,
                "visible": True,
                "will_validate": True,
                "constraint_satisfied": True,
                "locator": {
                    "strategy": "LABEL",
                    "value": "Email",
                    "exact": True,
                },
            },
            {
                "index": 1,
                "control_key": "contact-next",
                "tag": "button",
                "text": "Next",
                "visible": True,
                "locator": {
                    "strategy": "ROLE",
                    "value": "button",
                    "name": "Next",
                    "exact": True,
                },
            },
        ],
    )
    documents = _observation(
        page_type="DOCUMENT_UPLOAD",
        fingerprint="greenhouse-document-stage",
        visible_text="Greenhouse documents",
        url="https://boards.greenhouse.io/example/jobs/1#documents",
    )
    browser = _Browser(
        application,
        action_observations=[documents],
        expected_start_prefix="https://boards.greenhouse.io/",
    )
    service = SupervisedPortalService(
        SupervisedPortalRepository(session),
        browser,
        PortalCatalog(),
        enabled=True,
        submission_enabled=False,
        allowed_portals={PortalKind.GREENHOUSE},
    )
    run = service.start_reviewed_greenhouse(
        SupervisedPortalRunCreate(
            workflow_id="workflow-1",
            portal=PortalKind.GREENHOUSE,
            start_url=AnyHttpUrl(str(application.url)),
            profile_name="greenhouse-fixture",
        ),
        "d" * 64,
    )
    assert run.greenhouse_form is not None and run.greenhouse_form.ready_to_advance

    with pytest.raises(SupervisedPortalStateError, match="review changed"):
        service.navigate_reviewed_greenhouse_form(
            run.id,
            form_review_fingerprint="0" * 64,
            control_key="contact-next",
        )
    assert browser.executed == []

    completed = service.navigate_reviewed_greenhouse_form(
        run.id,
        form_review_fingerprint=run.greenhouse_form.review_fingerprint,
        control_key="contact-next",
    )
    assert completed.page_fingerprint == documents.page_fingerprint
    assert completed.greenhouse_form is not None
    assert completed.greenhouse_form.stage.value == "DOCUMENTS"
    assert completed.evidence[-1].verified
    assert completed.evidence[-1].action_kind is BrowserActionKind.CLICK
    assert len(browser.executed) == 1
    assert browser.state is BrowserSessionState.USER_TAKEOVER


def test_reviewed_greenhouse_navigation_failure_returns_control_without_retry(
    session: Session,
) -> None:
    application = _observation(
        page_type="APPLICATION_FORM",
        fingerprint="greenhouse-application-ready",
        visible_text="Greenhouse application",
        url="https://boards.greenhouse.io/example/jobs/1#application",
        controls=[
            {
                "index": 0,
                "control_key": "email",
                "tag": "input",
                "type": "email",
                "label": "Email",
                "label_source": "LABEL",
                "required": True,
                "native_required": True,
                "visible": True,
                "will_validate": True,
                "constraint_satisfied": True,
                "locator": {
                    "strategy": "LABEL",
                    "value": "Email",
                    "exact": True,
                },
            },
            {
                "index": 1,
                "control_key": "contact-next",
                "tag": "button",
                "text": "Next",
                "visible": True,
                "locator": {
                    "strategy": "ROLE",
                    "value": "button",
                    "name": "Next",
                    "exact": True,
                },
            },
        ],
    )
    escaped = application.model_copy(
        update={
            "url": "https://job-boards.greenhouse.io/example/jobs/1#application",
            "origin": "https://job-boards.greenhouse.io",
            "page_fingerprint": "greenhouse-escaped-ready",
        }
    )
    browser = _Browser(
        application,
        action_observations=[escaped],
        expected_start_prefix="https://boards.greenhouse.io/",
    )
    service = SupervisedPortalService(
        SupervisedPortalRepository(session),
        browser,
        PortalCatalog(),
        enabled=True,
        submission_enabled=False,
        allowed_portals={PortalKind.GREENHOUSE},
    )
    run = service.start_reviewed_greenhouse(
        SupervisedPortalRunCreate(
            workflow_id="workflow-1",
            portal=PortalKind.GREENHOUSE,
            start_url=AnyHttpUrl(str(application.url)),
            profile_name="greenhouse-fixture",
        ),
        "e" * 64,
    )
    assert run.greenhouse_form is not None and run.greenhouse_form.ready_to_advance

    completed = service.navigate_reviewed_greenhouse_form(
        run.id,
        form_review_fingerprint=run.greenhouse_form.review_fingerprint,
        control_key="contact-next",
    )

    assert completed.state is SupervisedPortalRunState.INTERVENTION_REQUIRED
    assert completed.disposition is SupervisedPortalDisposition.MANUAL_INTERVENTION_REQUIRED
    assert completed.intervention_reasons == [PortalInterventionReason.SITE_CHANGED]
    assert not completed.evidence[-1].verified
    assert completed.evidence[-1].action_kind is BrowserActionKind.CLICK
    assert len(browser.executed) == 1
    assert browser.state is BrowserSessionState.USER_TAKEOVER
