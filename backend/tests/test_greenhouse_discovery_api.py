from collections.abc import Generator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.job_discovery import get_public_board_client
from job_apply_pro.main import app
from job_apply_pro.portals.greenhouse import GreenhousePublicBoardClient
from job_apply_pro.storage.database import get_session
from test_greenhouse_discovery_import import command, profile
from test_greenhouse_public_client import BOARD, POSTING_ID, client_for, posting


@pytest.fixture
def api(session: Session) -> Generator[TestClient]:
    def get_database() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_session] = get_database
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_list_review_import_are_separate_explicit_local_operations(
    api: TestClient, session: Session
) -> None:
    profile_id = profile(session)
    app.dependency_overrides[get_public_board_client] = lambda: client_for({"jobs": [posting()]})
    listed = api.post("/api/v1/discovery/greenhouse/list", json={"board_token": BOARD})
    assert listed.status_code == 200 and listed.json()["jobs"][0]["posting_id"] == POSTING_ID
    app.dependency_overrides[get_public_board_client] = lambda: client_for(posting())
    reviewed = api.post(
        "/api/v1/discovery/greenhouse/review", json={"board_token": BOARD, "posting_id": POSTING_ID}
    )
    assert (
        reviewed.status_code == 200 and reviewed.json()["qualification_status"] == "NOT_EVALUATED"
    )
    imported = api.post(
        "/api/v1/discovery/greenhouse/import", json=command(profile_id).model_dump()
    )
    assert imported.status_code == 200 and imported.json()["outcome"] == "IMPORTED"
    workflow = imported.json()["workflow"]
    assert workflow["allowed_controls"] == []
    assert (
        api.post(
            f"/api/v1/workbench/workflows/{workflow['workflow_id']}/controls",
            json={"action": "ADVANCE"},
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "body",
    [
        {"board_token": "../private"},
        {"board_token": BOARD, "url": "http://127.0.0.1"},
        {"board_token": BOARD, "profile_id": "SECRET_PROFILE"},
        {"board_token": BOARD, "headers": {"Authorization": "SECRET_KEY"}},
    ],
)
def test_list_rejects_arbitrary_or_candidate_fields_before_provider(
    api: TestClient, body: object
) -> None:
    requests: list[httpx.Request] = []
    app.dependency_overrides[get_public_board_client] = lambda: client_for(posting(), requests)
    result = api.post("/api/v1/discovery/greenhouse/list", json=body)
    assert result.status_code == 422 and requests == []
    assert "SECRET" not in result.text


def test_provider_errors_do_not_return_raw_data(api: TestClient) -> None:
    app.dependency_overrides[get_public_board_client] = lambda: GreenhousePublicBoardClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500, text="PRIVATE_RAW_BODY"))
    )
    result = api.post(
        "/api/v1/discovery/greenhouse/review", json={"board_token": BOARD, "posting_id": POSTING_ID}
    )
    assert result.status_code == 502 and "PRIVATE" not in result.text
