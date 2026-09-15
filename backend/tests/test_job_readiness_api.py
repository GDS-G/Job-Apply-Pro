from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from job_apply_pro.api.routes import job_readiness as readiness_routes
from job_apply_pro.api.routes import knowledge as knowledge_routes
from job_apply_pro.api.routes.core import get_cipher
from job_apply_pro.api.routes.job_readiness import (
    get_greenhouse_application_service,
    get_readiness_service,
)
from job_apply_pro.config import Settings
from job_apply_pro.domain.browser import BrowserControlKind
from job_apply_pro.domain.greenhouse_form import (
    GREENHOUSE_FORM_UPLOAD_CONFIRMATION,
    GreenhouseFormAction,
)
from job_apply_pro.domain.knowledge import DocumentKind
from job_apply_pro.domain.portals import (
    PortalInterventionReason,
    PortalKind,
    SupervisedPortalDisposition,
    SupervisedPortalRunSnapshot,
    SupervisedPortalRunState,
)
from job_apply_pro.main import app
from job_apply_pro.services.greenhouse_application import GreenhouseApplicationService
from job_apply_pro.storage.database import get_session
from test_greenhouse_application import _action_run
from test_job_readiness import Fixture, fixture

__all__ = ["fixture"]


@pytest.fixture
def api(fixture: Fixture, session: Session) -> Generator[TestClient]:
    def get_database() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_session] = get_database
    app.dependency_overrides[get_readiness_service] = lambda: fixture.service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_api_runs_full_local_review_without_network(
    api: TestClient, fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Readiness must not make a network call")

    monkeypatch.setattr(httpx.Client, "request", forbidden)
    # TestClient overrides request itself; only ordinary provider clients are fenced.
    path = f"/api/v1/applications/{fixture.application_id}/job-review"
    initial = api.get(path)
    assert initial.status_code == 200 and initial.json()["status"] == "REQUIREMENTS_REVIEW"
    assert initial.json()["source"]["qualification_status"] == "NOT_EVALUATED"
    requirements = fixture.requirements()
    approved = api.post(f"{path}/requirements/approve", json=requirements.model_dump(mode="json"))
    assert approved.status_code == 200 and approved.json()["state"] == "DEDUPLICATED"
    qualification = fixture.qualification()
    evaluated = api.post(
        f"{path}/qualification/approve", json=qualification.model_dump(mode="json")
    )
    assert evaluated.status_code == 200 and evaluated.json()["state"] == "ELIGIBILITY_CHECKED"
    selected = api.post(f"{path}/resume/approve", json=fixture.selection().model_dump(mode="json"))
    assert selected.status_code == 200 and selected.json()["status"] == "READY"


def test_api_launches_only_the_exact_current_reviewed_greenhouse_application(
    api: TestClient, fixture: Fixture
) -> None:
    fixture.ready_to_select()
    fixture.service.approve_resume(fixture.selection())
    supervised = Mock()
    service = GreenhouseApplicationService(fixture.service, supervised)
    app.dependency_overrides[get_greenhouse_application_service] = lambda: service
    path = f"/api/v1/applications/{fixture.application_id}/job-review/greenhouse-launch"
    preview = api.get(path)
    assert preview.status_code == 200
    reviewed = preview.json()
    assert reviewed["application_id"] == fixture.application_id
    assert reviewed["start_origin"].endswith("greenhouse.io")
    assert reviewed["selected_document_version_id"] == fixture.version_id
    now = datetime.now(UTC)
    run = SupervisedPortalRunSnapshot(
        id="run-1",
        portal=PortalKind.GREENHOUSE,
        workflow_id=reviewed["workflow_id"],
        browser_session_id="browser-1",
        state=SupervisedPortalRunState.AWAITING_USER,
        current_url=reviewed["start_url"],
        allowed_origins=[reviewed["start_origin"]],
        page_fingerprint="page-1",
        disposition=SupervisedPortalDisposition.USER_ACTION_REQUIRED,
        intervention_reasons=[PortalInterventionReason.USER_TAKEOVER],
        evidence=[],
        created_at=now,
        updated_at=now,
    )
    supervised.start_reviewed_greenhouse.return_value = run
    body = {
        "application_id": fixture.application_id,
        "review_fingerprint": reviewed["review_fingerprint"],
        "profile_name": "greenhouse-test",
        "engine": "chromium",
        "confirmation_phrase": "OPEN REVIEWED GREENHOUSE APPLICATION",
    }
    started = api.post(path, json=body)
    assert started.status_code == 201 and started.json()["portal"] == "GREENHOUSE"
    command, recorded_fingerprint = supervised.start_reviewed_greenhouse.call_args.args
    assert command.workflow_id == reviewed["workflow_id"]
    assert str(command.start_url) == reviewed["start_url"]
    assert command.allowed_origins == []
    assert recorded_fingerprint == reviewed["review_fingerprint"]

    injected = api.post(
        path,
        json=body | {"start_url": "https://attacker.invalid/apply"},
    )
    assert injected.status_code == 422
    stale = api.post(path, json=body | {"review_fingerprint": "0" * 64})
    assert stale.status_code == 409
    assert supervised.start_reviewed_greenhouse.call_count == 1


def test_api_executes_only_the_exact_current_reviewed_greenhouse_form_action(
    api: TestClient, fixture: Fixture
) -> None:
    fixture.ready_to_select()
    fixture.service.approve_resume(fixture.selection())
    selected = fixture.knowledge.get_version_record(fixture.version_id)
    assert selected is not None
    reviewed_document = selected.model_copy(update={"file_name": "candidate-resume.pdf"})
    knowledge = Mock()
    knowledge.get_version_record.return_value = reviewed_document
    supervised = Mock()
    run = _action_run(
        fixture,
        action=GreenhouseFormAction.REVIEW_DOCUMENT_UPLOAD,
        control_kind=BrowserControlKind.FILE_UPLOAD,
        ready=False,
    )
    supervised.get.return_value = run
    supervised.upload_reviewed_greenhouse_document.return_value = run
    service = GreenhouseApplicationService(fixture.service, supervised, knowledge)
    app.dependency_overrides[get_greenhouse_application_service] = lambda: service
    assert run.greenhouse_form is not None
    path = f"/api/v1/applications/{fixture.application_id}/job-review/greenhouse-form-actions"
    request = {
        "application_id": fixture.application_id,
        "run_id": run.id,
        "action": "REVIEW_DOCUMENT_UPLOAD",
        "control_key": "resume",
        "form_review_fingerprint": run.greenhouse_form.review_fingerprint,
    }
    preview_response = api.post(f"{path}/preview", json=request)
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["selected_document_version_id"] == fixture.version_id
    assert preview["selected_document_file_name"] == "candidate-resume.pdf"

    executed = api.post(
        f"{path}/execute",
        json=request
        | {
            "preview_fingerprint": preview["preview_fingerprint"],
            "confirmation_phrase": GREENHOUSE_FORM_UPLOAD_CONFIRMATION,
        },
    )
    assert executed.status_code == 200
    supervised.upload_reviewed_greenhouse_document.assert_called_once_with(
        run.id,
        form_review_fingerprint=request["form_review_fingerprint"],
        control_key="resume",
        document=reviewed_document,
    )

    injected = api.post(
        f"{path}/preview",
        json=request | {"file_path": "C:/attacker-controlled/resume.pdf"},
    )
    assert injected.status_code == 422
    stale = api.post(
        f"{path}/execute",
        json=request
        | {
            "preview_fingerprint": "0" * 64,
            "confirmation_phrase": GREENHOUSE_FORM_UPLOAD_CONFIRMATION,
        },
    )
    assert stale.status_code == 409


def test_actual_dependency_needs_no_ai_registry_or_valid_provider_configuration(
    api: TestClient, fixture: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import SecretStr

    settings = Settings(
        document_data_dir=tmp_path / "documents",
        ai_config_json=SecretStr("invalid synthetic provider configuration"),
    )
    monkeypatch.setattr(readiness_routes, "get_settings", lambda: settings)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Local review must not construct an AI registry")

    monkeypatch.setattr(knowledge_routes, "build_ai_registry", forbidden)
    app.dependency_overrides.pop(get_readiness_service)
    app.dependency_overrides[get_cipher] = lambda: fixture.cipher
    result = api.get(f"/api/v1/applications/{fixture.application_id}/job-review")
    assert result.status_code == 200
    assert result.json()["status"] == "REQUIREMENTS_REVIEW"
    assert result.json()["evidence_claims"]


@pytest.mark.parametrize("mutation", ["extra", "identity", "phrase", "boolean"])
def test_api_rejects_unreviewed_or_mismatched_approval(
    api: TestClient, fixture: Fixture, mutation: str
) -> None:
    fixture.requirements()
    body = fixture.qualification().model_dump(mode="json")
    if mutation == "extra":
        body["inferred_requirement"] = "PRIVATE_UNTRUSTED_INPUT"
    elif mutation == "identity":
        body["application_id"] = "other-application"
    elif mutation == "phrase":
        body["confirmation_phrase"] = "PRIVATE_UNTRUSTED_INPUT"
    else:
        body["approve_eligibility"] = "true"
    result = api.post(
        f"/api/v1/applications/{fixture.application_id}/job-review/qualification/approve", json=body
    )
    assert result.status_code in {409, 422}
    assert "PRIVATE_UNTRUSTED_INPUT" not in result.text
    assert fixture.service.snapshot(fixture.application_id).state == "DEDUPLICATED"


def test_api_sanitizes_private_file_errors(
    api: TestClient, fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture.ready_to_select()

    def failure(*_args: object) -> bytes:
        raise OSError("PRIVATE_SYNTHETIC_PATH")

    monkeypatch.setattr(fixture.documents, "get_document_content", failure)
    result = api.post(
        f"/api/v1/applications/{fixture.application_id}/job-review/resume/preview",
        json={"application_id": fixture.application_id},
    )
    assert result.status_code == 409
    assert "PRIVATE_SYNTHETIC_PATH" not in result.text


@pytest.mark.parametrize("endpoint", ["snapshot", "preview", "approve"])
def test_unlinked_resume_non_ascii_corruption_is_a_sanitized_conflict(
    api: TestClient, fixture: Fixture, endpoint: str
) -> None:
    fixture.ready_to_select()
    imported = fixture.documents.import_document(
        fixture.profile_id,
        file_name="unlinked.txt",
        data=b"Synthetic alternate resume",
        kind=DocumentKind.RESUME,
        display_name="Alternate",
        variant_label="Unlinked evidence",
        job_family_tags=[],
        is_primary=False,
    )
    approval = fixture.selection()
    fixture.service.approve_resume(approval)
    version = fixture.knowledge.get_version_record(imported.version.id)
    assert version
    Path(version.storage_path).write_bytes(b"\xff")
    path = f"/api/v1/applications/{fixture.application_id}/job-review"
    if endpoint == "snapshot":
        result = api.get(path)
    elif endpoint == "preview":
        result = api.post(f"{path}/resume/preview", json={"application_id": fixture.application_id})
    else:
        result = api.post(f"{path}/resume/approve", json=approval.model_dump(mode="json"))
    assert result.status_code == 409
    assert (
        result.json()["detail"]
        == "Saved readiness evidence is unavailable or changed; reload and review"
    )
    assert version.storage_path not in result.text
