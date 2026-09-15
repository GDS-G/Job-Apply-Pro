"""Reviewed Greenhouse launch binding; all source and browser data is synthetic."""

from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest

from job_apply_pro.domain.greenhouse_application import (
    GREENHOUSE_APPLICATION_LAUNCH_CONFIRMATION,
    GREENHOUSE_APPLICATION_LAUNCH_POLICY,
    GreenhouseApplicationLaunchApproval,
    GreenhouseApplicationLaunchError,
)
from job_apply_pro.domain.portals import PortalKind, SupervisedPortalRunSnapshot
from job_apply_pro.services.greenhouse_application import GreenhouseApplicationService
from test_job_readiness import Fixture, fixture

__all__ = ["fixture"]


def _service(fixture: Fixture) -> tuple[GreenhouseApplicationService, Mock]:
    supervised = Mock()
    return GreenhouseApplicationService(fixture.service, supervised), supervised


def _ready(fixture: Fixture) -> None:
    fixture.ready_to_select()
    fixture.service.approve_resume(fixture.selection())


def test_launch_preview_requires_the_complete_current_readiness_chain(
    fixture: Fixture,
) -> None:
    service, supervised = _service(fixture)
    with pytest.raises(GreenhouseApplicationLaunchError, match="readiness chain"):
        service.preview(fixture.application_id)
    assert not supervised.mock_calls


def test_preview_binds_exact_source_reviews_and_immutable_resume(fixture: Fixture) -> None:
    _ready(fixture)
    service, supervised = _service(fixture)
    readiness = fixture.service.snapshot(fixture.application_id)
    preview = service.preview(fixture.application_id)
    assert readiness.source and readiness.requirements_review
    assert readiness.qualification_review and readiness.selection_review
    assert preview.application_id == fixture.application_id
    assert preview.workflow_id == readiness.workflow_id
    assert preview.profile_id == fixture.profile_id
    assert preview.start_url == readiness.source.source_url
    assert preview.start_origin == (
        f"https://{urlsplit(readiness.source.source_url or '').hostname}"
    )
    assert preview.selected_document_version_id == fixture.version_id
    assert preview.source_fingerprint == readiness.source_fingerprint
    assert preview.requirements_review_id == readiness.requirements_review.id
    assert preview.qualification_review_id == readiness.qualification_review.id
    assert preview.selection_review_id == readiness.selection_review.id
    assert preview.policy_version == GREENHOUSE_APPLICATION_LAUNCH_POLICY
    assert len(preview.review_fingerprint) == 64
    assert not supervised.mock_calls


def test_start_recomputes_preview_and_supplies_no_renderer_url_or_origin(
    fixture: Fixture,
) -> None:
    _ready(fixture)
    service, supervised = _service(fixture)
    preview = service.preview(fixture.application_id)
    expected = Mock(spec=SupervisedPortalRunSnapshot)
    supervised.start_reviewed_greenhouse.return_value = expected
    result = service.start(
        GreenhouseApplicationLaunchApproval(
            application_id=fixture.application_id,
            review_fingerprint=preview.review_fingerprint,
            profile_name="greenhouse-test",
            confirmation_phrase=GREENHOUSE_APPLICATION_LAUNCH_CONFIRMATION,
        )
    )
    assert result is expected
    command, recorded_fingerprint = supervised.start_reviewed_greenhouse.call_args.args
    readiness = fixture.service.snapshot(fixture.application_id)
    assert command.portal is PortalKind.GREENHOUSE
    assert command.workflow_id == readiness.workflow_id
    assert str(command.start_url) == preview.start_url
    assert command.allowed_origins == []
    assert command.profile_name == "greenhouse-test"
    assert recorded_fingerprint == preview.review_fingerprint


@pytest.mark.parametrize("mutation", ["fingerprint", "confirmation", "readiness"])
def test_changed_or_unconfirmed_launch_never_starts_browser(
    fixture: Fixture, mutation: str
) -> None:
    _ready(fixture)
    service, supervised = _service(fixture)
    preview = service.preview(fixture.application_id)
    approval = GreenhouseApplicationLaunchApproval(
        application_id=fixture.application_id,
        review_fingerprint=preview.review_fingerprint,
        profile_name="greenhouse-test",
        confirmation_phrase=GREENHOUSE_APPLICATION_LAUNCH_CONFIRMATION,
    )
    if mutation == "fingerprint":
        approval = approval.model_copy(update={"review_fingerprint": "0" * 64})
    elif mutation == "confirmation":
        approval = approval.model_copy(update={"confirmation_phrase": "OPEN ANY URL"})
    else:
        fixture.requirements(["MANDATORY", "MANDATORY"])
    with pytest.raises(GreenhouseApplicationLaunchError):
        service.start(approval)
    supervised.start_reviewed_greenhouse.assert_not_called()
