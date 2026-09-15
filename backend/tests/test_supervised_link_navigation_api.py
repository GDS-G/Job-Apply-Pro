from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from job_apply_pro.api.routes.portals import get_supervised_portal_service
from job_apply_pro.config import get_settings
from job_apply_pro.domain.portals import (
    LinkedInJobIdentityReview,
    PortalInterventionReason,
    PortalKind,
    SupervisedPortalDisposition,
    SupervisedPortalLinkNavigationPreview,
    SupervisedPortalRunSnapshot,
    SupervisedPortalRunState,
)
from job_apply_pro.main import create_app
from job_apply_pro.services.supervised_portals import SupervisedPortalService

_RUN_ID = "6f3cf568-ec3b-4d8c-bccb-49ca1db4bb35"
_SESSION_ID = "6a17312e-f9d4-4aca-a8f6-833b459cc678"
_CONTROL_KEY = "reviewed-job-link"


@pytest.fixture
def link_navigation_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Mock]]:
    monkeypatch.setenv("JAP_API_TOKEN", "synthetic-link-navigation-token")
    get_settings.cache_clear()
    service = Mock(spec=SupervisedPortalService)
    application = create_app()
    application.dependency_overrides[get_supervised_portal_service] = lambda: service
    client = TestClient(
        application,
        headers={"X-Job-Apply-Pro-Token": "synthetic-link-navigation-token"},
    )
    try:
        yield client, service
    finally:
        client.close()
        application.dependency_overrides.clear()
        get_settings.cache_clear()


def _preview() -> SupervisedPortalLinkNavigationPreview:
    return SupervisedPortalLinkNavigationPreview(
        run_id=_RUN_ID,
        browser_session_id=_SESSION_ID,
        control_key=_CONTROL_KEY,
        label="View reviewed job",
        source_page_type="JOB_SEARCH_RESULTS",
        target_origin="https://www.linkedin.com",
        target_path="/jobs/view/456",
        page_fingerprint="linkedin-search-v1",
        review_fingerprint="a" * 64,
        notice="Approval navigates directly to the exact reviewed target.",
    )


def _run() -> SupervisedPortalRunSnapshot:
    now = datetime(2026, 9, 15, 20, tzinfo=UTC)
    return SupervisedPortalRunSnapshot(
        id=_RUN_ID,
        portal=PortalKind.LINKEDIN,
        workflow_id="workflow-1",
        browser_session_id=_SESSION_ID,
        state=SupervisedPortalRunState.AWAITING_USER,
        current_url="https://www.linkedin.com/jobs/view/456",
        allowed_origins=["https://www.linkedin.com"],
        page_fingerprint="linkedin-detail-v2",
        disposition=SupervisedPortalDisposition.USER_ACTION_REQUIRED,
        intervention_reasons=[PortalInterventionReason.USER_TAKEOVER],
        evidence=[],
        observed_controls=[],
        reviewed_links=[],
        created_at=now,
        updated_at=now,
    )


def _identity_review() -> LinkedInJobIdentityReview:
    return LinkedInJobIdentityReview(
        run_id=_RUN_ID,
        browser_session_id=_SESSION_ID,
        source_url="https://www.linkedin.com/jobs/view/456",
        external_id="456",
        title="Senior Platform Engineer",
        page_fingerprint="linkedin-detail-v2",
        review_fingerprint="b" * 64,
        captured_at=datetime(2026, 9, 15, 20, tzinfo=UTC),
    )


def test_linkedin_job_identity_api_returns_only_the_backend_review(
    link_navigation_api: tuple[TestClient, Mock],
) -> None:
    client, service = link_navigation_api
    review = _identity_review()
    service.review_linkedin_job_identity.return_value = review

    response = client.get(f"/api/v1/portals/supervised/runs/{_RUN_ID}/linkedin/job-identity")

    assert response.status_code == 200
    assert response.json() == review.model_dump(mode="json")
    service.review_linkedin_job_identity.assert_called_once_with(_RUN_ID)


def test_link_navigation_api_previews_then_approves_exact_backend_review(
    link_navigation_api: tuple[TestClient, Mock],
) -> None:
    client, service = link_navigation_api
    preview = _preview()
    run = _run()
    service.preview_reviewed_link_navigation.return_value = preview
    service.navigate_reviewed_link.return_value = run
    path = f"/api/v1/portals/supervised/runs/{_RUN_ID}/links/{_CONTROL_KEY}/navigation"

    reviewed = client.post(
        f"{path}/preview",
        json={"expected_page_fingerprint": "linkedin-search-v1"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json() == preview.model_dump(mode="json")
    review = service.preview_reviewed_link_navigation.call_args.args[2]
    assert review.expected_page_fingerprint == "linkedin-search-v1"

    approved = client.post(
        f"{path}/approve",
        json={
            "expected_review_fingerprint": preview.review_fingerprint,
            "confirmation_phrase": "NAVIGATE REVIEWED LINK",
        },
    )
    assert approved.status_code == 200
    assert approved.json() == run.model_dump(mode="json")
    approval = service.navigate_reviewed_link.call_args.args[2]
    assert approval.expected_review_fingerprint == preview.review_fingerprint
    assert approval.confirmation_phrase == "NAVIGATE REVIEWED LINK"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "expected_review_fingerprint": "a" * 64,
            "confirmation_phrase": "NAVIGATE REVIEWED LINK",
            "url": "https://untrusted.invalid",
        },
        {
            "expected_review_fingerprint": "a" * 64,
            "confirmation_phrase": "CLICK REVIEWED LINK",
        },
    ],
)
def test_link_navigation_api_rejects_injected_or_wrong_approval(
    link_navigation_api: tuple[TestClient, Mock], payload: dict[str, str]
) -> None:
    client, service = link_navigation_api
    response = client.post(
        f"/api/v1/portals/supervised/runs/{_RUN_ID}/links/{_CONTROL_KEY}/navigation/approve",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Request validation failed; check required fields and supported values"
    }
    service.navigate_reviewed_link.assert_not_called()
