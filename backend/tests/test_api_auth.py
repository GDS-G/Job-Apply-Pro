import pytest
from fastapi.testclient import TestClient

from job_apply_pro.config import get_settings
from job_apply_pro.main import create_app


def test_configured_local_api_token_protects_privileged_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAP_API_TOKEN", "test-local-token")
    get_settings.cache_clear()
    client = TestClient(create_app())
    try:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/runtime/status").status_code == 401

        response = client.get(
            "/api/v1/runtime/status",
            headers={"X-Job-Apply-Pro-Token": "test-local-token"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "version": "0.3.0-alpha.1",
            "automation_enabled": False,
            "authenticated": True,
        }
    finally:
        get_settings.cache_clear()
