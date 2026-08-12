from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shutil import which
from threading import Thread
from typing import cast

import pytest
from pydantic import AnyHttpUrl
from sqlalchemy.orm import Session

from job_apply_pro.browser.client import BrowserWorkerClient
from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionKind,
    BrowserControlKind,
    BrowserEngine,
    BrowserSessionCreate,
    BrowserSessionState,
    BrowserVerification,
    LocatorStrategy,
    SemanticLocator,
    VerificationKind,
)
from job_apply_pro.domain.candidate import CandidateProfileCreate, ContactDetails
from job_apply_pro.domain.workbench import MockWorkflowCreate
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.browser_runtime import BrowserPolicyError, BrowserRuntimeService
from job_apply_pro.services.core import CoreService
from job_apply_pro.services.workbench import WorkbenchService
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    BrowserRuntimeRepository,
    CandidateRepository,
    CheckpointRepository,
    JobRepository,
    WorkbenchRepository,
)


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_GET(self) -> None:
        server_port = cast(ThreadingHTTPServer, self.server).server_port
        pages = {
            "/start": """
                <body data-page-type="CANDIDATE_IDENTITY">
                  <h1>Candidate identity</h1>
                  <label>Full name <input name="full_name" required
                    oninput="localStorage.setItem('full_name', this.value)"></label>
                  <label>Email <input name="email" type="email" required
                    oninput="localStorage.setItem('email', this.value)"></label>
                  <label>Portal password <input name="portal_password" type="password"
                    value="fixture-secret"></label>
                  <button type="button" onclick="location.href='/experience'">Continue</button>
                  <script>
                    full_name.value = localStorage.getItem('full_name') || '';
                    email.value = localStorage.getItem('email') || '';
                  </script>
                </body>
            """,
            "/experience": """
                <body data-page-type="EXPERIENCE">
                  <h1>Experience</h1>
                  <label>Years of experience <input name="years" required
                    oninput="localStorage.setItem('years', this.value)"></label>
                  <label><input name="authorized" type="checkbox"> Authorized to work</label>
                  <button type="button" onclick="location.href='/review'">Continue</button>
                  <script>years.value = localStorage.getItem('years') || '';</script>
                </body>
            """,
            "/review": """
                <body data-page-type="REVIEW">
                  <h1>Review application</h1>
                  <button type="button" onclick="location.href='/complete'">Submit fixture</button>
                </body>
            """,
            "/complete": """
                <body data-page-type="CONFIRMATION">
                  <h1>Fixture application complete</h1>
                  <p role="status">Confirmation number FIXTURE-104</p>
                </body>
            """,
            "/escape": f"""
                <body data-page-type="REVIEW">
                  <h1>Origin escape fixture</h1>
                  <button type="button"
                    onclick="location.href='http://localhost:{server_port}/complete'">
                    Leave allowed origin
                  </button>
                </body>
            """,
        }
        body = pages.get(self.path)
        if body is None:
            self.send_error(404)
            return
        payload = (
            f"<!doctype html><html><head><title>Job Apply Pro Fixture</title></head>{body}</html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@contextmanager
def _fixture_site() -> Generator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _create_workflow(session: Session) -> str:
    candidates = CandidateRepository(session)
    jobs = JobRepository(session)
    applications = ApplicationRepository(session)
    profile = CoreService(
        candidates,
        jobs,
        applications,
        CheckpointRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"b" * 32)),
    ).create_candidate(
        CandidateProfileCreate(
            display_name="Browser fixture profile",
            contact=ContactDetails(
                full_name="Browser User",
                email="browser@example.com",
            ),
        )
    )
    return (
        WorkbenchService(
            candidates,
            jobs,
            applications,
            WorkbenchRepository(session),
        )
        .start_mock_workflow(
            MockWorkflowCreate(
                profile_id=profile.id,
                employer="Fixture Systems",
                title="Browser Engineer",
            )
        )
        .workflow_id
    )


def _service(
    session: Session, tmp_path: Path, worker: BrowserWorkerClient
) -> BrowserRuntimeService:
    return BrowserRuntimeService(
        BrowserRuntimeRepository(session),
        WorkbenchRepository(session),
        CheckpointRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"r" * 32)),
        worker,
        browser_data_dir=tmp_path / "browser",
        browser_artifact_dir=tmp_path / "artifacts",
        default_headless=True,
        automation_enabled=False,
    )


def _label(value: str) -> SemanticLocator:
    return SemanticLocator(strategy=LocatorStrategy.LABEL, value=value)


def _button(name: str) -> SemanticLocator:
    return SemanticLocator(strategy=LocatorStrategy.ROLE, value="button", name=name)


def _fill(label: str, value: str) -> BrowserAction:
    locator = _label(label)
    return BrowserAction(
        kind=BrowserActionKind.FILL,
        locator=locator,
        value=value,
        intended_result=f"Set {label}",
        verification=BrowserVerification(
            kind=VerificationKind.VALUE_EQUALS,
            value=value,
            locator=locator,
        ),
    )


def _click_to(name: str, path: str) -> BrowserAction:
    return BrowserAction(
        kind=BrowserActionKind.CLICK,
        locator=_button(name),
        intended_result=f"Navigate to {path}",
        verification=BrowserVerification(
            kind=VerificationKind.URL_CONTAINS,
            value=path,
        ),
    )


def _channel_available(engine: BrowserEngine) -> bool:
    candidates = {
        BrowserEngine.CHROME: [
            Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        ],
        BrowserEngine.EDGE: [
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
            Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        ],
    }
    command = "google-chrome" if engine is BrowserEngine.CHROME else "microsoft-edge"
    return which(command) is not None or any(path.is_file() for path in candidates[engine])


def test_browser_runtime_rejects_external_origins_when_production_is_locked(
    session: Session, tmp_path: Path
) -> None:
    workflow_id = _create_workflow(session)
    worker = BrowserWorkerClient(timeout_seconds=10)
    try:
        service = _service(session, tmp_path, worker)
        with pytest.raises(BrowserPolicyError, match="External browser origins"):
            service.create_session(
                BrowserSessionCreate(
                    workflow_id=workflow_id,
                    start_url=AnyHttpUrl("https://example.com/apply"),
                    profile_name="blocked-external",
                )
            )
        assert not worker.running
    finally:
        worker.close()


def test_multi_page_fixture_is_verified_traced_and_restartable(
    session: Session, tmp_path: Path
) -> None:
    workflow_id = _create_workflow(session)
    worker = BrowserWorkerClient(timeout_seconds=75)
    service = _service(session, tmp_path, worker)
    try:
        with _fixture_site() as origin:
            started = service.create_session(
                BrowserSessionCreate(
                    workflow_id=workflow_id,
                    start_url=AnyHttpUrl(f"{origin}/start"),
                    engine=BrowserEngine.CHROMIUM,
                    profile_name="fixture-profile",
                )
            )
            assert started.state is BrowserSessionState.ACTIVE
            assert started.observation is not None
            assert started.observation.page_type == "CANDIDATE_IDENTITY"
            assert Path(started.observation.screenshot_path).is_file()
            full_name = next(
                control
                for control in started.observation.controls
                if control.field_name == "full_name"
            )
            assert full_name.kind is BrowserControlKind.TEXT
            assert full_name.label == "Full name"
            assert full_name.required
            assert len(full_name.control_key) == 32
            assert full_name.locator == _label("Full name")
            assert all(control.input_type != "password" for control in started.observation.controls)

            assert service.execute_action(started.id, _fill("Full name", "Browser User")).verified
            assert service.execute_action(
                started.id, _fill("Email", "browser@example.com")
            ).verified
            assert service.execute_action(started.id, _click_to("Continue", "/experience")).verified
            experience = service.execute_action(started.id, _fill("Years of experience", "7"))
            assert experience.verified
            authorized = next(
                control
                for control in experience.observation.controls
                if control.field_name == "authorized"
            )
            assert authorized.kind is BrowserControlKind.CHECKBOX
            assert authorized.label == "Authorized to work"

            restarted = service.restart(started.id)
            assert restarted.state is BrowserSessionState.ACTIVE
            assert "/experience" in restarted.current_url
            persisted = service.execute_action(started.id, _fill("Years of experience", "7"))
            assert persisted.verified

            assert service.execute_action(started.id, _click_to("Continue", "/review")).verified
            completed = service.execute_action(started.id, _click_to("Submit fixture", "/complete"))
            assert completed.verified
            assert completed.observation.page_type == "CONFIRMATION"
            assert "FIXTURE-104" in completed.observation.visible_text

            stopped = service.stop(started.id)
            assert stopped.state is BrowserSessionState.STOPPED
            assert stopped.trace_path is not None
            assert Path(stopped.trace_path).is_file()
            assert stopped.action_count == 7
            assert len(service.list_actions(started.id)) == 7
    finally:
        worker.close()


def test_runtime_moves_to_takeover_when_a_page_escapes_the_origin_allowlist(
    session: Session, tmp_path: Path
) -> None:
    workflow_id = _create_workflow(session)
    worker = BrowserWorkerClient(timeout_seconds=75)
    service = _service(session, tmp_path, worker)
    try:
        with _fixture_site() as origin:
            started = service.create_session(
                BrowserSessionCreate(
                    workflow_id=workflow_id,
                    start_url=AnyHttpUrl(f"{origin}/escape"),
                    engine=BrowserEngine.CHROMIUM,
                    profile_name="origin-escape-profile",
                )
            )

            with pytest.raises(BrowserPolicyError, match="escaped"):
                service.execute_action(
                    started.id,
                    _click_to("Leave allowed origin", "/complete"),
                )

            assert service.get_session(started.id).state is BrowserSessionState.USER_TAKEOVER
    finally:
        worker.close()


@pytest.mark.parametrize("engine", [BrowserEngine.CHROME, BrowserEngine.EDGE])
def test_installed_browser_channels_keep_persistent_profiles_across_restart(
    engine: BrowserEngine, session: Session, tmp_path: Path
) -> None:
    if not _channel_available(engine):
        pytest.skip(f"{engine.value} browser channel is not installed")
    workflow_id = _create_workflow(session)
    worker = BrowserWorkerClient(timeout_seconds=75)
    service = _service(session, tmp_path, worker)
    try:
        with _fixture_site() as origin:
            started = service.create_session(
                BrowserSessionCreate(
                    workflow_id=workflow_id,
                    start_url=AnyHttpUrl(f"{origin}/start"),
                    engine=engine,
                    profile_name=f"{engine.value}-fixture-profile",
                )
            )
            assert service.execute_action(
                started.id, _fill("Full name", f"{engine.value} user")
            ).verified
            restarted = service.restart(started.id)
            assert restarted.observation is not None
            assert restarted.observation.page_type == "CANDIDATE_IDENTITY"
            assert service.execute_action(
                started.id, _fill("Full name", f"{engine.value} user")
            ).verified
            stopped = service.stop(started.id)
            assert stopped.trace_path is not None
            assert Path(stopped.trace_path).is_file()
    finally:
        worker.close()
