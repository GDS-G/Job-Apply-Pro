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
        assert client.get("/api/v1/browser/sessions").status_code == 401
        assert client.get("/api/v1/knowledge/profiles/profile-1/snapshot").status_code == 401
        assert client.get("/api/v1/ai/status").status_code == 401
        assert client.get("/api/v1/portals/runs").status_code == 401
        assert (
            client.get(
                "/api/v1/portals/supervised/runs/run-1/applications/application-1/field-coverage"
            ).status_code
            == 401
        )
        assert client.get("/api/v1/challenges/sessions").status_code == 401
        assert client.get("/api/v1/communications/integrations").status_code == 401
        assert client.get("/api/v1/communications/configuration").status_code == 401
        assert client.post("/api/v1/communications/configuration/validate").status_code == 401
        assert client.post("/api/v1/communications/configuration/import").status_code == 401
        assert client.delete("/api/v1/communications/configuration").status_code == 401
        assert (
            client.post("/api/v1/communications/providers/GMAIL/messages/sync").status_code == 401
        )
        assert (
            client.post(
                "/api/v1/communications/providers/GOOGLE_CALENDAR/calendar/sync"
            ).status_code
            == 401
        )
        assert client.get("/api/v1/operations/dashboard").status_code == 401
        assert client.get("/api/v1/operations/diagnostics").status_code == 401
        assert client.post("/api/v1/operations/backup-schedules/run-due").status_code == 401

        response = client.get(
            "/api/v1/runtime/status",
            headers={"X-Job-Apply-Pro-Token": "test-local-token"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "version": "0.38.0-alpha.1",
            "automation_enabled": False,
            "browser_runtime_available": True,
            "candidate_knowledge_available": True,
            "ai_gateway_available": True,
            "portal_vertical_slice_available": True,
            "communication_scheduling_available": True,
            "operations_dashboard_available": True,
            "production_hardening_available": True,
            "authenticated": True,
        }
    finally:
        get_settings.cache_clear()
