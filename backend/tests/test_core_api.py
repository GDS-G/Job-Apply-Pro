from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.core import get_cipher
from job_apply_pro.main import app
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.storage.database import get_session


def test_core_api_round_trip(session: Session) -> None:
    def override_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_cipher] = lambda: SensitiveDataCipher(StaticKeyProvider(b"e" * 32))
    client = TestClient(app)
    try:
        candidate_response = client.post(
            "/api/v1/candidates",
            json={
                "display_name": "API profile",
                "contact": {"full_name": "API User", "email": "api@example.com"},
            },
        )
        assert candidate_response.status_code == 201
        candidate = candidate_response.json()

        job_response = client.post(
            "/api/v1/jobs",
            json={
                "source": "api-board",
                "external_id": "api-1",
                "employer": "API Corp",
                "title": "API Engineer",
                "description_hash": "f" * 64,
            },
        )
        assert job_response.status_code == 201
        job = job_response.json()

        application_response = client.post(
            "/api/v1/applications",
            json={
                "workflow_id": "api-workflow",
                "profile_id": candidate["id"],
                "job_id": job["id"],
            },
        )
        assert application_response.status_code == 201

        checkpoint_response = client.post(
            "/api/v1/workflows/api-workflow/checkpoints",
            json={
                "state": "FORM_MAPPED",
                "page_fingerprint": "sha256:api-form",
                "payload": {"field": "email", "value": "api@example.com"},
            },
        )
        assert checkpoint_response.status_code == 201
        assert (
            client.get("/api/v1/workflows/api-workflow/checkpoints/latest").json()["sequence"] == 1
        )

        mock_response = client.post(
            "/api/v1/workbench/mock-workflows",
            json={
                "profile_id": candidate["id"],
                "employer": "Workbench API Corp",
                "title": "Desktop Engineer",
            },
        )
        assert mock_response.status_code == 201
        mock = mock_response.json()
        assert mock["state"] == "DEDUPLICATED"

        pause_response = client.post(
            f"/api/v1/workbench/workflows/{mock['workflow_id']}/controls",
            json={"action": "PAUSE"},
        )
        assert pause_response.status_code == 200
        assert pause_response.json()["state"] == "USER_TAKEOVER"
    finally:
        app.dependency_overrides.clear()
