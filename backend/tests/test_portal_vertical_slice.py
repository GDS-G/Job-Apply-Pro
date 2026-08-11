from __future__ import annotations

import hashlib
import json
from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

import pytest
from pydantic import AnyHttpUrl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_apply_pro.browser.client import BrowserWorkerClient
from job_apply_pro.domain.candidate import CandidateProfileCreate, ContactDetails
from job_apply_pro.domain.jobs import JobCreate
from job_apply_pro.domain.knowledge import ClaimPermittedUse, ClaimReview, DocumentKind
from job_apply_pro.domain.portals import ReferencePortalRunCreate, SubmissionApproval
from job_apply_pro.domain.workflow import WorkflowState
from job_apply_pro.portals.reference_ats import PortalContractError, ReferenceAtsAdapter
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.browser_runtime import BrowserRuntimeService
from job_apply_pro.services.core import CoreService
from job_apply_pro.services.knowledge import CandidateKnowledgeService
from job_apply_pro.services.portals import PortalApprovalError, ReferencePortalService
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.models import FitScoreRow, JobRequirementRow, PortalRunRow
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    BrowserRuntimeRepository,
    CandidateRepository,
    CheckpointRepository,
    JobRepository,
    PortalRunRepository,
    WorkbenchRepository,
)


class _ReferenceAtsHandler(BaseHTTPRequestHandler):
    origin = ""

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/jobs":
            payload = json.dumps(
                [
                    {
                        "external_id": "REF-101",
                        "employer": "Fixture Systems",
                        "title": "Python Automation Engineer",
                        "location": "Chicago, IL",
                        "description": "Build reliable browser automation.",
                        "requirements": ["Python", "Playwright"],
                        "source_url": f"{self.origin}/jobs/REF-101",
                    }
                ]
            ).encode()
            self._send(payload, "application/json")
            return
        pages = {
            "/jobs/REF-101": """
                <body data-page-type="JOB_DETAIL">
                  <h1>Reference ATS job</h1>
                  <p>Job ID</p><p>REF-101</p>
                  <p>Employer</p><p>Fixture Systems</p>
                  <p>Title</p><p>Python Automation Engineer</p>
                  <p>Location</p><p>Chicago, IL</p>
                  <p>Description</p><p>Build reliable browser automation.</p>
                  <h2>Requirements</h2><p>Python</p><p>Playwright</p>
                  <button type="button" onclick="location.href='/application/identity'">
                    Apply now
                  </button>
                </body>
            """,
            "/application/identity": """
                <body data-page-type="CANDIDATE_IDENTITY">
                  <h1>Candidate identity</h1>
                  <label for="full-name">Full name</label>
                  <input id="full-name" required data-canonical-field="FULL_NAME">
                  <label for="email">Email</label>
                  <input id="email" type="email" required data-canonical-field="EMAIL">
                  <label for="resume">Resume</label>
                  <input id="resume" type="file" required data-canonical-field="RESUME"
                    onchange="document.querySelector('[role=status]').textContent =
                      this.files[0] ? this.files[0].name : ''">
                  <p role="status"></p>
                  <button type="button" onclick="location.href='/application/experience'">
                    Continue
                  </button>
                </body>
            """,
            "/application/experience": """
                <body data-page-type="EXPERIENCE">
                  <h1>Experience</h1>
                  <label for="years">Years of relevant experience</label>
                  <input id="years" required data-canonical-field="EXPERIENCE_YEARS">
                  <label><input id="authorized" type="checkbox" required
                    data-canonical-field="WORK_AUTHORIZATION"> Authorized to work</label>
                  <label for="interest">Why are you interested?</label>
                  <textarea id="interest" required data-canonical-field="CUSTOM"></textarea>
                  <button type="button" onclick="location.href='/application/review'">
                    Review application
                  </button>
                </body>
            """,
            "/application/review": """
                <body data-page-type="REVIEW">
                  <h1>Review application</h1>
                  <p>All required fields and resume are ready.</p>
                  <button type="button" onclick="location.href='/application/confirmation'">
                    Submit application
                  </button>
                </body>
            """,
            "/application/confirmation": """
                <body data-page-type="CONFIRMATION">
                  <h1>Application received</h1>
                  <p role="status">Confirmation number: REF-CONF-104</p>
                </body>
            """,
        }
        body = pages.get(path)
        if body is None:
            self.send_error(404)
            return
        payload = (
            "<!doctype html><html><head><title>Reference ATS</title></head>" + body + "</html>"
        ).encode()
        self._send(payload, "text/html; charset=utf-8")

    def _send(self, payload: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@contextmanager
def _reference_ats() -> Generator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ReferenceAtsHandler)
    origin = f"http://127.0.0.1:{server.server_port}"
    _ReferenceAtsHandler.origin = origin
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield origin
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _service(
    session: Session, tmp_path: Path, worker: BrowserWorkerClient
) -> tuple[ReferencePortalService, str]:
    cipher = SensitiveDataCipher(StaticKeyProvider(b"p" * 32))
    candidates = CandidateRepository(session)
    jobs = JobRepository(session)
    applications = ApplicationRepository(session)
    checkpoints = CheckpointRepository(session)
    knowledge_repository = CandidateKnowledgeRepository(session)
    core = CoreService(candidates, jobs, applications, checkpoints, cipher)
    profile = core.create_candidate(
        CandidateProfileCreate(
            display_name="Portal fixture profile",
            contact=ContactDetails(
                full_name="Portal User",
                email="portal@example.com",
            ),
        )
    )
    knowledge = CandidateKnowledgeService(
        knowledge_repository,
        candidates,
        cipher,
        document_data_dir=tmp_path / "documents",
        document_max_bytes=1_000_000,
    )
    imported = knowledge.import_document(
        profile.id,
        file_name="portal-resume.txt",
        data=(
            b"Portal User\nSenior Automation Engineer | Jan 2019 - Dec 2025\n"
            b"Skills: Python, Playwright, browser automation\n"
        ),
        kind=DocumentKind.RESUME,
        display_name="Automation resume",
        variant_label="Automation",
        job_family_tags=["python", "automation"],
        is_primary=True,
    )
    for claim in imported.proposed_claims:
        if claim.canonical_key in {
            "skill.python",
            "skill.playwright",
        } or claim.canonical_key.startswith("experience."):
            knowledge.review_claim(
                claim.id,
                ClaimReview(
                    approved=True,
                    permitted_use=ClaimPermittedUse.APPLICATIONS,
                ),
            )
    browser = BrowserRuntimeService(
        BrowserRuntimeRepository(session),
        WorkbenchRepository(session),
        checkpoints,
        cipher,
        worker,
        browser_data_dir=tmp_path / "browser",
        browser_artifact_dir=tmp_path / "artifacts",
        default_headless=True,
        automation_enabled=False,
    )
    return (
        ReferencePortalService(
            core=core,
            jobs=jobs,
            applications=applications,
            workbench=WorkbenchRepository(session),
            knowledge=knowledge_repository,
            runs=PortalRunRepository(session),
            browser=browser,
            cipher=cipher,
        ),
        profile.id,
    )


def test_reference_ats_completes_discovery_to_confirmed_tracking(
    session: Session, tmp_path: Path
) -> None:
    worker = BrowserWorkerClient(timeout_seconds=75)
    try:
        service, profile_id = _service(session, tmp_path, worker)
        with _reference_ats() as origin:
            JobRepository(session).add(
                JobCreate(
                    source="reference-ats",
                    external_id="REF-101",
                    employer="Fixture Systems",
                    title="Python Automation Engineer",
                    location="Chicago, IL",
                    source_url=AnyHttpUrl(f"{origin}/jobs/REF-101"),
                    description_hash=hashlib.sha256(
                        b"Build reliable browser automation."
                    ).hexdigest(),
                )
            )
            prepared = service.prepare(
                ReferencePortalRunCreate(
                    profile_id=profile_id,
                    portal_origin=AnyHttpUrl(origin),
                    query="Python automation",
                    minimum_fit_score=1,
                )
            )
            assert prepared.state is WorkflowState.READY_TO_SUBMIT
            assert prepared.deduplicated
            assert prepared.qualification.score == 1
            assert {mapping.canonical_field for mapping in prepared.field_mappings} >= {
                "FULL_NAME",
                "EMAIL",
                "RESUME",
                "EXPERIENCE_YEARS",
                "WORK_AUTHORIZATION",
                "CUSTOM",
            }
            staged = tmp_path / "artifacts" / prepared.browser_session_id / "staged-uploads"
            assert not staged.exists()
            with pytest.raises(PortalApprovalError, match="fingerprint"):
                service.confirm(
                    prepared.id,
                    SubmissionApproval(
                        review_fingerprint="wrong-fingerprint",
                        confirmation_phrase="SUBMIT REFERENCE APPLICATION",
                    ),
                )
            completed = service.confirm(
                prepared.id,
                SubmissionApproval(
                    review_fingerprint=prepared.review_fingerprint,
                    confirmation_phrase="SUBMIT REFERENCE APPLICATION",
                ),
            )
            assert completed.state is WorkflowState.TRACKING_ACTIVE
            assert completed.submission_evidence is not None
            assert completed.submission_evidence.confirmation_code == "REF-CONF-104"
            assert completed.trace_path is not None
            assert Path(completed.trace_path).is_file()
            assert not (Path(completed.trace_path).parent / "staged-uploads").exists()
            workflow = WorkbenchRepository(session).get_snapshot(completed.workflow_id)
            assert workflow is not None
            states = [event.next_state for event in workflow.events]
            assert states == [
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
            ]
            assert session.scalar(select(func.count(JobRequirementRow.id))) == 2
            assert session.scalar(select(func.count(FitScoreRow.id))) == 1
            assert session.get(PortalRunRow, completed.id) is not None
            assert service.get(completed.id) == completed
    finally:
        worker.close()


def test_reference_adapter_rejects_non_loopback_discovery() -> None:
    with pytest.raises(PortalContractError, match="loopback"):
        ReferenceAtsAdapter().discover_jobs("https://jobs.example.com", "engineer")
