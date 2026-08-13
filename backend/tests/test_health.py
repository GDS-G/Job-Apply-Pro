from fastapi.testclient import TestClient

from job_apply_pro.main import app


def test_health_reports_portal_vertical_slice_build() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "job-apply-pro-backend",
        "version": "0.46.0-alpha.1",
        "build": "Observed Form Control Capture",
        "environment": "development",
    }


def test_dashboard_keeps_live_automation_disabled() -> None:
    response = TestClient(app).get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    assert response.json()["automation_enabled"] is False
