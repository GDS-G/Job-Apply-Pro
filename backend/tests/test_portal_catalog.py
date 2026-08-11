import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from job_apply_pro.config import get_settings
from job_apply_pro.domain.portals import (
    PortalCapability,
    PortalExecutionStrategy,
    PortalKind,
    PortalReplayCase,
)
from job_apply_pro.main import create_app
from job_apply_pro.portals.catalog import PortalCatalog, PortalCatalogError


def _cases() -> list[PortalReplayCase]:
    path = Path(__file__).parent / "fixtures" / "portal_replays.json"
    return [PortalReplayCase.model_validate(item) for item in json.loads(path.read_text())]


def test_named_portal_catalog_and_sanitized_replays() -> None:
    catalog = PortalCatalog()
    definitions = catalog.definitions()
    assert {item.kind for item in definitions} == {
        PortalKind.LINKEDIN,
        PortalKind.INDEED,
        PortalKind.MONSTER,
        PortalKind.CAREERBUILDER,
        PortalKind.DICE,
        PortalKind.ZIPRECRUITER,
        PortalKind.GLASSDOOR,
        PortalKind.COMPANY_CAREERS,
        PortalKind.WORKDAY,
        PortalKind.TALEO,
        PortalKind.GREENHOUSE,
    }
    assert all(item.strategy is PortalExecutionStrategy.GENERIC_AGENT for item in definitions)
    assert all(not item.production_enabled for item in definitions)
    assert all(len(item.replay_validated_page_types) == 4 for item in definitions)
    assert all(not item.live_validated_page_types for item in definitions)
    expected_fingerprints = {
        "JOB_SEARCH_RESULTS",
        "JOB_DETAIL",
        "LOGIN",
        "MFA",
        "CAPTCHA",
        "APPLICATION_FORM",
        "DOCUMENT_UPLOAD",
        "QUESTIONNAIRE",
        "ASSESSMENT",
        "SUBMISSION_REVIEW",
        "CONFIRMATION",
    }
    assert all(
        {rule.page_type for rule in item.fingerprints} == expected_fingerprints
        for item in definitions
    )
    assert all(rule.minimum_confidence == 1 for item in definitions for rule in item.fingerprints)
    metrics = catalog.run_replays(_cases())
    assert all(item.cases == item.passed == 5 for item in metrics)
    assert all(item.fingerprint_accuracy == 1 for item in metrics)
    assert all(item.confirmation_cases == item.confirmation_passed == 2 for item in metrics)
    assert all(item.confirmation_false_positives == 0 for item in metrics)
    assert all(item.required_replay_coverage for item in metrics)
    assert all(
        set(item.page_types_exercised)
        == {"JOB_SEARCH_RESULTS", "JOB_DETAIL", "APPLICATION_FORM", "CONFIRMATION"}
        for item in metrics
    )
    assert all(
        set(item.capabilities_exercised)
        == {
            PortalCapability.SEARCH,
            PortalCapability.JOB_EXTRACTION,
            PortalCapability.MULTI_PAGE_FORM,
            PortalCapability.CONFIRMATION,
        }
        for item in metrics
    )


def test_fingerprints_and_confirmation_fail_closed() -> None:
    catalog = PortalCatalog()
    with pytest.raises(PortalCatalogError, match="confidence"):
        catalog.identify(
            url="https://www.linkedin.com/jobs/search",
            page_type="JOB_SEARCH_RESULTS",
            visible_text="unrelated page",
            control_labels=[],
            page_fingerprint="fingerprint",
        )
    with pytest.raises(PortalCatalogError, match="confidence"):
        catalog.identify(
            url="https://www.linkedin.com/jobs/search",
            page_type=None,
            visible_text="LinkedIn",
            control_labels=[],
            page_fingerprint="brand-only-fingerprint",
        )
    match = catalog.identify(
        url="https://boards.greenhouse.io/example/jobs/1",
        page_type="JOB_DETAIL",
        visible_text="Greenhouse role Apply",
        control_labels=["Apply"],
        page_fingerprint="fingerprint",
    )
    assert match.portal is PortalKind.GREENHOUSE
    assert match.capability is PortalCapability.JOB_EXTRACTION
    classified = catalog.identify(
        url="https://boards.greenhouse.io/example/confirmation",
        page_type=None,
        visible_text="Greenhouse application received",
        control_labels=["Done"],
        page_fingerprint="confirmation-fingerprint",
    )
    assert classified.page_type == "CONFIRMATION"
    assert classified.capability is PortalCapability.CONFIRMATION
    login = catalog.identify(
        url="https://www.linkedin.com/login",
        page_type=None,
        visible_text="LinkedIn Sign in",
        control_labels=["Email"],
        page_fingerprint="login-fingerprint",
    )
    assert login.page_type == "LOGIN"
    assert login.requires_user_intervention
    assert not catalog.verify_confirmation(
        PortalKind.GREENHOUSE,
        page_type="CONFIRMATION",
        visible_text="Application submitted",
        confirmation_identifier=None,
    )
    assert catalog.verify_confirmation(
        PortalKind.GREENHOUSE,
        page_type="CONFIRMATION",
        visible_text="Application submitted",
        confirmation_identifier="GH-123",
    )


def test_portal_catalog_api_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JAP_API_TOKEN", "portal-token")
    get_settings.cache_clear()
    client = TestClient(create_app())
    try:
        assert client.get("/api/v1/portals/catalog").status_code == 401
        response = client.get(
            "/api/v1/portals/catalog",
            headers={"X-Job-Apply-Pro-Token": "portal-token"},
        )
        assert response.status_code == 200
        assert len(response.json()) == 11
        classified = client.post(
            "/api/v1/portals/identify",
            json={
                "url": "https://boards.greenhouse.io/example/confirmation",
                "visible_text": "Greenhouse application received",
                "control_labels": ["Done"],
                "page_fingerprint": "api-confirmation",
            },
            headers={"X-Job-Apply-Pro-Token": "portal-token"},
        )
        assert classified.status_code == 200
        assert classified.json()["page_type"] == "CONFIRMATION"
        replay = client.post(
            "/api/v1/portals/replays/validate",
            json=[item.model_dump(mode="json") for item in _cases()],
            headers={"X-Job-Apply-Pro-Token": "portal-token"},
        )
        assert replay.status_code == 200
        assert all(item["fingerprint_accuracy"] == 1 for item in replay.json())
        assert all(item["confirmation_false_positives"] == 0 for item in replay.json())
    finally:
        get_settings.cache_clear()
