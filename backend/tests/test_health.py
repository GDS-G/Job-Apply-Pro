from fastapi.testclient import TestClient

from job_apply_pro.main import app


def test_health_reports_candidate_knowledge_build() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "job-apply-pro-backend",
        "version": "0.5.0-alpha.1",
        "build": "Candidate Knowledge",
        "environment": "development",
    }


def test_dashboard_keeps_live_automation_disabled() -> None:
    response = TestClient(app).get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    assert response.json()["automation_enabled"] is False
