from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from job_apply_pro.domain.applications import ApplicationCreate
from job_apply_pro.domain.jobs import JobCreate
from job_apply_pro.domain.workflow import WorkflowState
from job_apply_pro.main import app
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    JobRepository,
    WorkflowEventRepository,
)
from test_greenhouse_discovery_import import command, profile, service


@pytest.fixture
def api(session: Session) -> Generator[TestClient]:
    def get_database() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_session] = get_database
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def transition(current: str = "DISCOVERED", next_state: str = "DEDUPLICATED") -> dict[str, str]:
    return {
        "current_state": current,
        "next_state": next_state,
        "actor": "caller",
        "cause": "Caller assertion is not source-specific evidence",
        "verification": "PASSED",
    }


@pytest.mark.parametrize(
    ("current", "next_state"),
    [
        ("DEDUPLICATED", "SCORED"),
        ("SUBMISSION_ATTEMPTED", "SUBMISSION_CONFIRMED"),
    ],
)
def test_public_transition_cannot_fabricate_imported_history(
    api: TestClient, session: Session, current: str, next_state: str
) -> None:
    imported = service(session).import_job(command(profile(session)))
    assert imported.workflow
    workflow = imported.workflow
    events = WorkflowEventRepository(session)
    before = events.list_for_workflow(workflow.workflow_id)
    result = api.post(
        f"/api/v1/workflows/{workflow.workflow_id}/transitions",
        json=transition(current, next_state),
    )
    assert result.status_code == 409
    assert "synthetic workbench" in result.json()["detail"]
    assert events.list_for_workflow(workflow.workflow_id) == before
    saved = ApplicationRepository(session).get(workflow.application_id)
    assert saved and saved.state is WorkflowState.DEDUPLICATED


@pytest.mark.parametrize("source", ["manual", "reference-ats", "greenhouse-public"])
def test_public_transition_requires_synthetic_source(
    api: TestClient, session: Session, source: str
) -> None:
    profile_id = profile(session)
    job = JobRepository(session).add(
        JobCreate(
            source=source,
            external_id="fixture",
            employer="Synthetic fixture",
            title="Fixture role",
            description_hash="a" * 64,
        )
    )
    application = ApplicationRepository(session).add(
        ApplicationCreate(workflow_id="fixture", profile_id=profile_id, job_id=job.id)
    )
    result = api.post("/api/v1/workflows/fixture/transitions", json=transition())
    assert result.status_code == 409
    assert WorkflowEventRepository(session).list_for_workflow("fixture") == []
    assert ApplicationRepository(session).get(application.id) == application


def test_unknown_workflow_cannot_seed_fabricated_history(api: TestClient, session: Session) -> None:
    result = api.post("/api/v1/workflows/missing/transitions", json=transition())
    assert result.status_code == 409
    assert WorkflowEventRepository(session).list_for_workflow("missing") == []


def test_synthetic_direct_events_require_actual_application_state(
    api: TestClient, session: Session
) -> None:
    profile_id = profile(session)
    job = JobRepository(session).add(
        JobCreate(
            source="workbench-mock",
            external_id="fixture",
            employer="Synthetic fixture",
            title="Fixture role",
            description_hash="a" * 64,
        )
    )
    ApplicationRepository(session).add(
        ApplicationCreate(workflow_id="fixture", profile_id=profile_id, job_id=job.id)
    )
    forged = api.post(
        "/api/v1/workflows/fixture/transitions",
        json=transition("SUBMISSION_ATTEMPTED", "SUBMISSION_CONFIRMED"),
    )
    assert forged.status_code == 409
    assert WorkflowEventRepository(session).list_for_workflow("fixture") == []
    allowed = api.post("/api/v1/workflows/fixture/transitions", json=transition())
    assert allowed.status_code == 201
    assert [
        event.next_state for event in WorkflowEventRepository(session).list_for_workflow("fixture")
    ] == [WorkflowState.DEDUPLICATED]


def test_core_application_creation_cannot_set_state_or_update_existing_import(
    api: TestClient, session: Session
) -> None:
    profile_id = profile(session)
    imported = service(session).import_job(command(profile_id))
    assert imported.workflow and imported.job
    workflow = imported.workflow
    before = WorkflowEventRepository(session).list_for_workflow(workflow.workflow_id)
    payload = {
        "workflow_id": workflow.workflow_id,
        "profile_id": profile_id,
        "job_id": imported.job.id,
        "state": "SUBMISSION_CONFIRMED",
    }
    result = api.post("/api/v1/applications", json=payload)
    assert result.status_code == 409
    session.rollback()
    assert (
        api.put(f"/api/v1/applications/{workflow.application_id}", json=payload).status_code == 405
    )
    assert (
        api.patch(f"/api/v1/applications/{workflow.application_id}", json=payload).status_code
        == 405
    )
    saved = ApplicationRepository(session).get(workflow.application_id)
    assert saved and saved.state is WorkflowState.DEDUPLICATED
    assert WorkflowEventRepository(session).list_for_workflow(workflow.workflow_id) == before
    created = api.post("/api/v1/applications", json={**payload, "workflow_id": "other-workflow"})
    assert created.status_code == 201
    assert created.json()["state"] == "DISCOVERED"
    assert WorkflowEventRepository(session).list_for_workflow("other-workflow") == []
