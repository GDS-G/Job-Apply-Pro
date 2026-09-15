from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from job_apply_pro.api.routes.browser import get_browser_service
from job_apply_pro.config import get_settings
from job_apply_pro.domain.browser import (
    BrowserEngine,
    BrowserProfileRetirementPreview,
    BrowserProfileRetirementResult,
    BrowserProfileSnapshot,
    BrowserProfileState,
)
from job_apply_pro.main import create_app
from job_apply_pro.services.browser_runtime import BrowserRuntimeService

_PROFILE_NAME = "workday-tenant-a"
_UPDATED_AT = datetime(2026, 9, 15, 18, tzinfo=UTC)


@pytest.fixture
def retirement_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Mock]]:
    monkeypatch.setenv("JAP_API_TOKEN", "synthetic-profile-retirement-token")
    get_settings.cache_clear()
    service = Mock(spec=BrowserRuntimeService)
    application = create_app()
    application.dependency_overrides[get_browser_service] = lambda: service
    client = TestClient(
        application,
        headers={"X-Job-Apply-Pro-Token": "synthetic-profile-retirement-token"},
    )
    try:
        yield client, service
    finally:
        client.close()
        application.dependency_overrides.clear()
        get_settings.cache_clear()


def _profile() -> BrowserProfileSnapshot:
    return BrowserProfileSnapshot(
        engine=BrowserEngine.EDGE,
        profile_name=_PROFILE_NAME,
        state=BrowserProfileState.AVAILABLE,
        allowed_origins=["https://tenant.wd5.myworkdayjobs.com"],
        session_count=2,
        last_used_at=_UPDATED_AT,
    )


def _preview() -> BrowserProfileRetirementPreview:
    return BrowserProfileRetirementPreview(
        **_profile().model_dump(),
        file_count=12,
        directory_count=4,
        total_bytes=4096,
        review_fingerprint="b" * 64,
        notice="Review local browser profile retirement.",
    )


def test_profile_retirement_api_lists_previews_and_approves_exact_profile(
    retirement_api: tuple[TestClient, Mock],
) -> None:
    client, service = retirement_api
    profile = _profile()
    preview = _preview()
    result = BrowserProfileRetirementResult(
        engine=BrowserEngine.EDGE,
        profile_name=_PROFILE_NAME,
        removed=True,
        retired_at=_UPDATED_AT,
        notice="Local browser profile data was removed.",
    )
    service.list_profiles.return_value = [profile]
    service.preview_profile_retirement.return_value = preview
    service.retire_profile.return_value = result
    path = f"/api/v1/browser/profiles/msedge/{_PROFILE_NAME}/retirement"

    listed = client.get("/api/v1/browser/profiles")
    assert listed.status_code == 200
    assert listed.json() == [profile.model_dump(mode="json")]

    reviewed = client.post(f"{path}/preview")
    assert reviewed.status_code == 200
    assert reviewed.json() == preview.model_dump(mode="json")
    service.preview_profile_retirement.assert_called_once_with(BrowserEngine.EDGE, _PROFILE_NAME)

    approved = client.post(
        f"{path}/approve",
        json={
            "engine": "msedge",
            "profile_name": _PROFILE_NAME,
            "expected_review_fingerprint": preview.review_fingerprint,
            "confirmation_phrase": "RETIRE LOCAL BROWSER PROFILE",
        },
    )
    assert approved.status_code == 200
    assert approved.json() == result.model_dump(mode="json")
    approval = service.retire_profile.call_args.args[0]
    assert approval.engine is BrowserEngine.EDGE
    assert approval.profile_name == _PROFILE_NAME
    assert approval.expected_review_fingerprint == preview.review_fingerprint


def test_profile_retirement_api_rejects_route_body_mismatch(
    retirement_api: tuple[TestClient, Mock],
) -> None:
    client, service = retirement_api
    response = client.post(
        f"/api/v1/browser/profiles/msedge/{_PROFILE_NAME}/retirement/approve",
        json={
            "engine": "chromium",
            "profile_name": _PROFILE_NAME,
            "expected_review_fingerprint": "b" * 64,
            "confirmation_phrase": "RETIRE LOCAL BROWSER PROFILE",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Browser profile retirement approval does not match the route"
    }
    service.retire_profile.assert_not_called()


def test_profile_retirement_api_rejects_malformed_profile_name(
    retirement_api: tuple[TestClient, Mock],
) -> None:
    client, service = retirement_api
    response = client.post("/api/v1/browser/profiles/msedge/not%20allowed/retirement/preview")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Request validation failed; check required fields and supported values"
    }
    service.preview_profile_retirement.assert_not_called()
