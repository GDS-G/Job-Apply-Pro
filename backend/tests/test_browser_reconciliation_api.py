from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from job_apply_pro.api.routes.browser import get_browser_service
from job_apply_pro.config import get_settings
from job_apply_pro.domain.browser import (
    BrowserActionKind,
    BrowserFieldReconciliationPreview,
    BrowserFieldReconciliationResult,
    BrowserNavigationReconciliationPreview,
    BrowserNavigationReconciliationResult,
    BrowserSubmissionReconciliationPreview,
    BrowserSubmissionReconciliationResult,
    BrowserUploadReconciliationPreview,
    BrowserUploadReconciliationResult,
    VerificationKind,
)
from job_apply_pro.main import create_app
from job_apply_pro.services.browser_runtime import BrowserRuntimeService

_OPERATION_ID = "64a4cc96-07d1-4a0e-8000-a74811a13c0e"
_ATTEMPT_ID = "19c70be6-ea1b-4c71-b668-d359f7ce4b06"
_SESSION_ID = "5fdf419a-0771-4d75-99d2-c76ba2f89719"


@pytest.fixture
def reconciliation_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Mock]]:
    monkeypatch.setenv("JAP_API_TOKEN", "synthetic-reconciliation-token")
    get_settings.cache_clear()
    service = Mock(spec=BrowserRuntimeService)
    application = create_app()
    application.dependency_overrides[get_browser_service] = lambda: service
    client = TestClient(
        application,
        headers={"X-Job-Apply-Pro-Token": "synthetic-reconciliation-token"},
    )
    try:
        yield client, service
    finally:
        client.close()
        application.dependency_overrides.clear()
        get_settings.cache_clear()


def _preview() -> BrowserFieldReconciliationPreview:
    return BrowserFieldReconciliationPreview(
        operation_id=_OPERATION_ID,
        attempt_id=_ATTEMPT_ID,
        session_id=_SESSION_ID,
        action_kind=BrowserActionKind.FILL,
        verification_kind=VerificationKind.VALUE_EQUALS,
        page_fingerprint="greenhouse:questionnaire:ab12cd34",
        review_fingerprint="a" * 64,
        notice="The prior field write is visible and may be recorded without retrying it.",
    )


def test_reconciliation_api_previews_then_approves_the_exact_review(
    reconciliation_api: tuple[TestClient, Mock],
) -> None:
    client, service = reconciliation_api
    preview = _preview()
    result = BrowserFieldReconciliationResult(
        operation_id=_OPERATION_ID,
        attempt_id=_ATTEMPT_ID,
        session_id=_SESSION_ID,
        action_kind=BrowserActionKind.FILL,
        page_fingerprint=preview.page_fingerprint,
        reconciliation_kind="BROWSER_FIELD_VALUE_CONFIRMED",
        reconciled_at=datetime(2026, 9, 15, 18, tzinfo=UTC),
        notice="Verified field outcome recorded without repeating the action.",
    )
    service.preview_field_reconciliation.return_value = preview
    service.approve_field_reconciliation.return_value = result
    path = f"/api/v1/browser/sessions/{_SESSION_ID}/field-reconciliations/{_OPERATION_ID}"

    reviewed = client.post(f"{path}/preview")
    assert reviewed.status_code == 200
    assert reviewed.json() == preview.model_dump(mode="json")
    service.preview_field_reconciliation.assert_called_once_with(_SESSION_ID, _OPERATION_ID)

    approved = client.post(
        f"{path}/approve",
        json={
            "operation_id": _OPERATION_ID,
            "expected_review_fingerprint": preview.review_fingerprint,
            "confirmation_phrase": "RECONCILE VERIFIED FIELD",
        },
    )
    assert approved.status_code == 200
    assert approved.json() == result.model_dump(mode="json")
    approval = service.approve_field_reconciliation.call_args.args[1]
    assert approval.operation_id == _OPERATION_ID
    assert approval.expected_review_fingerprint == preview.review_fingerprint
    assert approval.confirmation_phrase == "RECONCILE VERIFIED FIELD"


def test_reconciliation_api_rejects_route_body_mismatch_before_service_dispatch(
    reconciliation_api: tuple[TestClient, Mock],
) -> None:
    client, service = reconciliation_api
    response = client.post(
        f"/api/v1/browser/sessions/{_SESSION_ID}/field-reconciliations/{_OPERATION_ID}/approve",
        json={
            "operation_id": "05d34e54-311a-47b4-8bd1-8d35d0334956",
            "expected_review_fingerprint": "a" * 64,
            "confirmation_phrase": "RECONCILE VERIFIED FIELD",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Browser reconciliation operation id does not match the route"
    }
    service.approve_field_reconciliation.assert_not_called()


def test_reconciliation_api_rejects_malformed_path_ids_before_service_dispatch(
    reconciliation_api: tuple[TestClient, Mock],
) -> None:
    client, service = reconciliation_api
    response = client.post(
        f"/api/v1/browser/sessions/not-a-session/field-reconciliations/{_OPERATION_ID}/preview"
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Request validation failed; check required fields and supported values"
    }
    service.preview_field_reconciliation.assert_not_called()


def test_navigation_reconciliation_api_previews_then_approves_exact_review(
    reconciliation_api: tuple[TestClient, Mock],
) -> None:
    client, service = reconciliation_api
    preview = BrowserNavigationReconciliationPreview(
        operation_id=_OPERATION_ID,
        attempt_id=_ATTEMPT_ID,
        session_id=_SESSION_ID,
        source_page_type="APPLICATION_FORM",
        result_page_type="DOCUMENT_UPLOAD",
        result_page_fingerprint="greenhouse-documents-v2",
        review_fingerprint="b" * 64,
        notice="A recognized later form stage is visible.",
    )
    result = BrowserNavigationReconciliationResult(
        operation_id=_OPERATION_ID,
        attempt_id=_ATTEMPT_ID,
        session_id=_SESSION_ID,
        source_page_type=preview.source_page_type,
        result_page_type=preview.result_page_type,
        result_page_fingerprint=preview.result_page_fingerprint,
        reconciliation_kind="BROWSER_NAVIGATION_CONFIRMED",
        reconciled_at=datetime(2026, 9, 15, 19, tzinfo=UTC),
        notice="Reviewed navigation outcome recorded without retrying it.",
    )
    service.preview_navigation_reconciliation.return_value = preview
    service.approve_navigation_reconciliation.return_value = result
    path = f"/api/v1/browser/sessions/{_SESSION_ID}/navigation-reconciliations/{_OPERATION_ID}"

    reviewed = client.post(f"{path}/preview")
    assert reviewed.status_code == 200
    assert reviewed.json() == preview.model_dump(mode="json")
    service.preview_navigation_reconciliation.assert_called_once_with(_SESSION_ID, _OPERATION_ID)

    approved = client.post(
        f"{path}/approve",
        json={
            "operation_id": _OPERATION_ID,
            "expected_review_fingerprint": preview.review_fingerprint,
            "confirmation_phrase": "RECONCILE REVIEWED NAVIGATION",
        },
    )
    assert approved.status_code == 200
    assert approved.json() == result.model_dump(mode="json")
    approval = service.approve_navigation_reconciliation.call_args.args[1]
    assert approval.operation_id == _OPERATION_ID
    assert approval.confirmation_phrase == "RECONCILE REVIEWED NAVIGATION"


def test_navigation_reconciliation_api_rejects_route_body_mismatch(
    reconciliation_api: tuple[TestClient, Mock],
) -> None:
    client, service = reconciliation_api
    response = client.post(
        f"/api/v1/browser/sessions/{_SESSION_ID}/navigation-reconciliations/{_OPERATION_ID}/approve",
        json={
            "operation_id": "05d34e54-311a-47b4-8bd1-8d35d0334956",
            "expected_review_fingerprint": "b" * 64,
            "confirmation_phrase": "RECONCILE REVIEWED NAVIGATION",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Browser navigation reconciliation operation id does not match the route"
    }
    service.approve_navigation_reconciliation.assert_not_called()


def test_upload_reconciliation_api_previews_then_approves_exact_review(
    reconciliation_api: tuple[TestClient, Mock],
) -> None:
    client, service = reconciliation_api
    preview = BrowserUploadReconciliationPreview(
        operation_id=_OPERATION_ID,
        attempt_id=_ATTEMPT_ID,
        session_id=_SESSION_ID,
        file_name="candidate-resume.pdf",
        page_type="DOCUMENT_UPLOAD",
        result_page_fingerprint="greenhouse-documents-uploaded-v2",
        review_fingerprint="c" * 64,
        notice="The exact reviewed filename is visible on the same form stage.",
    )
    result = BrowserUploadReconciliationResult(
        operation_id=_OPERATION_ID,
        attempt_id=_ATTEMPT_ID,
        session_id=_SESSION_ID,
        file_name=preview.file_name,
        page_type=preview.page_type,
        result_page_fingerprint=preview.result_page_fingerprint,
        reconciliation_kind="BROWSER_UPLOAD_CONFIRMED",
        reconciled_at=datetime(2026, 9, 15, 20, tzinfo=UTC),
        notice="Reviewed upload outcome recorded without uploading again.",
    )
    service.preview_upload_reconciliation.return_value = preview
    service.approve_upload_reconciliation.return_value = result
    path = f"/api/v1/browser/sessions/{_SESSION_ID}/upload-reconciliations/{_OPERATION_ID}"

    reviewed = client.post(f"{path}/preview")
    assert reviewed.status_code == 200
    assert reviewed.json() == preview.model_dump(mode="json")
    service.preview_upload_reconciliation.assert_called_once_with(_SESSION_ID, _OPERATION_ID)

    approved = client.post(
        f"{path}/approve",
        json={
            "operation_id": _OPERATION_ID,
            "expected_review_fingerprint": preview.review_fingerprint,
            "confirmation_phrase": "RECONCILE REVIEWED UPLOAD",
        },
    )
    assert approved.status_code == 200
    assert approved.json() == result.model_dump(mode="json")
    approval = service.approve_upload_reconciliation.call_args.args[1]
    assert approval.operation_id == _OPERATION_ID
    assert approval.confirmation_phrase == "RECONCILE REVIEWED UPLOAD"


def test_upload_reconciliation_api_rejects_route_body_mismatch(
    reconciliation_api: tuple[TestClient, Mock],
) -> None:
    client, service = reconciliation_api
    response = client.post(
        f"/api/v1/browser/sessions/{_SESSION_ID}/upload-reconciliations/{_OPERATION_ID}/approve",
        json={
            "operation_id": "05d34e54-311a-47b4-8bd1-8d35d0334956",
            "expected_review_fingerprint": "c" * 64,
            "confirmation_phrase": "RECONCILE REVIEWED UPLOAD",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Browser upload reconciliation operation id does not match the route"
    }
    service.approve_upload_reconciliation.assert_not_called()


def test_submission_reconciliation_api_previews_then_approves_exact_review(
    reconciliation_api: tuple[TestClient, Mock],
) -> None:
    client, service = reconciliation_api
    preview = BrowserSubmissionReconciliationPreview(
        operation_id=_OPERATION_ID,
        attempt_id=_ATTEMPT_ID,
        session_id=_SESSION_ID,
        source_page_type="SUBMISSION_REVIEW",
        result_page_type="CONFIRMATION",
        result_page_fingerprint="greenhouse-confirmation-v2",
        review_fingerprint="d" * 64,
        notice="An identifier-backed Greenhouse confirmation is visible.",
    )
    result = BrowserSubmissionReconciliationResult(
        operation_id=_OPERATION_ID,
        attempt_id=_ATTEMPT_ID,
        session_id=_SESSION_ID,
        source_page_type=preview.source_page_type,
        result_page_type=preview.result_page_type,
        result_page_fingerprint=preview.result_page_fingerprint,
        reconciliation_kind="BROWSER_SUBMISSION_CONFIRMED",
        reconciled_at=datetime(2026, 9, 15, 21, tzinfo=UTC),
        notice="Confirmed submission recorded without submitting again.",
    )
    service.preview_submission_reconciliation.return_value = preview
    service.approve_submission_reconciliation.return_value = result
    path = f"/api/v1/browser/sessions/{_SESSION_ID}/submission-reconciliations/{_OPERATION_ID}"

    reviewed = client.post(f"{path}/preview")
    assert reviewed.status_code == 200
    assert reviewed.json() == preview.model_dump(mode="json")
    service.preview_submission_reconciliation.assert_called_once_with(_SESSION_ID, _OPERATION_ID)

    approved = client.post(
        f"{path}/approve",
        json={
            "operation_id": _OPERATION_ID,
            "expected_review_fingerprint": preview.review_fingerprint,
            "confirmation_phrase": "RECONCILE CONFIRMED SUBMISSION",
        },
    )
    assert approved.status_code == 200
    assert approved.json() == result.model_dump(mode="json")
    approval = service.approve_submission_reconciliation.call_args.args[1]
    assert approval.operation_id == _OPERATION_ID
    assert approval.confirmation_phrase == "RECONCILE CONFIRMED SUBMISSION"


def test_submission_reconciliation_api_rejects_route_body_mismatch(
    reconciliation_api: tuple[TestClient, Mock],
) -> None:
    client, service = reconciliation_api
    response = client.post(
        f"/api/v1/browser/sessions/{_SESSION_ID}/submission-reconciliations/{_OPERATION_ID}/approve",
        json={
            "operation_id": "05d34e54-311a-47b4-8bd1-8d35d0334956",
            "expected_review_fingerprint": "d" * 64,
            "confirmation_phrase": "RECONCILE CONFIRMED SUBMISSION",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Browser submission reconciliation operation id does not match the route"
    }
    service.approve_submission_reconciliation.assert_not_called()
