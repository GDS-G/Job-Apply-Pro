"""Reviewed Greenhouse launch binding; all source and browser data is synthetic."""

from datetime import UTC, datetime
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest

from job_apply_pro.domain.browser import BrowserControlKind
from job_apply_pro.domain.greenhouse_application import (
    GREENHOUSE_APPLICATION_LAUNCH_CONFIRMATION,
    GREENHOUSE_APPLICATION_LAUNCH_POLICY,
    GreenhouseApplicationLaunchApproval,
    GreenhouseApplicationLaunchError,
)
from job_apply_pro.domain.greenhouse_form import (
    GREENHOUSE_FORM_NAVIGATION_CONFIRMATION,
    GREENHOUSE_FORM_UPLOAD_CONFIRMATION,
    GreenhouseControlContract,
    GreenhouseFormAction,
    GreenhouseFormActionApproval,
    GreenhouseFormActionRequest,
    GreenhouseFormContractAssessment,
    GreenhouseFormStage,
    GreenhousePostconditionKind,
)
from job_apply_pro.domain.portals import (
    PortalInterventionReason,
    PortalKind,
    SupervisedPortalDisposition,
    SupervisedPortalRunSnapshot,
    SupervisedPortalRunState,
)
from job_apply_pro.services.greenhouse_application import GreenhouseApplicationService
from test_job_readiness import Fixture, fixture

__all__ = ["fixture"]


def _service(fixture: Fixture) -> tuple[GreenhouseApplicationService, Mock]:
    supervised = Mock()
    return (
        GreenhouseApplicationService(fixture.service, supervised, fixture.knowledge),
        supervised,
    )


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


def _action_run(
    fixture: Fixture,
    *,
    action: GreenhouseFormAction,
    control_kind: BrowserControlKind,
    ready: bool,
) -> SupervisedPortalRunSnapshot:
    launch = GreenhouseApplicationService(fixture.service).preview(fixture.application_id)
    review = "e" * 64
    control_key = "resume" if action is GreenhouseFormAction.REVIEW_DOCUMENT_UPLOAD else "next"
    now = datetime.now(UTC)
    return SupervisedPortalRunSnapshot(
        id="greenhouse-run-1",
        portal=PortalKind.GREENHOUSE,
        workflow_id=launch.workflow_id,
        browser_session_id="browser-1",
        state=SupervisedPortalRunState.AWAITING_USER,
        current_url=launch.start_url,
        allowed_origins=[launch.start_origin],
        page_fingerprint="greenhouse-page-1",
        disposition=SupervisedPortalDisposition.USER_ACTION_REQUIRED,
        intervention_reasons=[PortalInterventionReason.USER_TAKEOVER],
        evidence=[],
        greenhouse_form=GreenhouseFormContractAssessment(
            policy_version="greenhouse-form-execution-contract/1",
            page_fingerprint="greenhouse-page-1",
            page_type=(
                "DOCUMENT_UPLOAD"
                if control_kind is BrowserControlKind.FILE_UPLOAD
                else "APPLICATION_FORM"
            ),
            stage=(
                GreenhouseFormStage.DOCUMENTS
                if control_kind is BrowserControlKind.FILE_UPLOAD
                else GreenhouseFormStage.APPLICATION
            ),
            required_control_count=1,
            satisfied_required_count=1 if ready else 0,
            review_field_count=0,
            upload_review_count=0 if ready else 1,
            manual_intervention_count=0,
            navigation_control_key=control_key if ready else None,
            navigation_label="Next" if ready else None,
            ready_to_advance=ready,
            controls=[
                GreenhouseControlContract(
                    control_key=control_key,
                    label="Resume" if control_kind is BrowserControlKind.FILE_UPLOAD else "Next",
                    control_kind=control_kind,
                    required=control_kind is BrowserControlKind.FILE_UPLOAD,
                    blocking=not ready,
                    action=action,
                    postcondition=(
                        GreenhousePostconditionKind.UPLOAD_FILE_NAME_OBSERVED
                        if control_kind is BrowserControlKind.FILE_UPLOAD
                        else GreenhousePostconditionKind.NEXT_STAGE_OBSERVED
                    ),
                    reason="Synthetic reviewed action contract.",
                )
            ],
            limitations=[],
            review_fingerprint=review,
        ),
        created_at=now,
        updated_at=now,
    )


def test_navigation_action_preview_and_execution_bind_current_application_and_run(
    fixture: Fixture,
) -> None:
    _ready(fixture)
    supervised = Mock()
    run = _action_run(
        fixture,
        action=GreenhouseFormAction.REVIEW_NAVIGATION,
        control_kind=BrowserControlKind.BUTTON,
        ready=True,
    )
    supervised.get.return_value = run
    supervised.navigate_reviewed_greenhouse_form.return_value = run
    service = GreenhouseApplicationService(fixture.service, supervised, fixture.knowledge)
    assert run.greenhouse_form is not None
    request = GreenhouseFormActionRequest(
        application_id=fixture.application_id,
        run_id=run.id,
        action=GreenhouseFormAction.REVIEW_NAVIGATION,
        control_key="next",
        form_review_fingerprint=run.greenhouse_form.review_fingerprint,
    )
    preview = service.preview_form_action(request)
    assert preview.workflow_id == run.workflow_id
    assert preview.control_label == "Next"
    assert preview.selected_document_version_id is None
    assert len(preview.preview_fingerprint) == 64

    with pytest.raises(GreenhouseApplicationLaunchError, match="confirmation"):
        service.execute_form_action(
            GreenhouseFormActionApproval(
                **request.model_dump(),
                preview_fingerprint=preview.preview_fingerprint,
                confirmation_phrase="ADVANCE ANY FORM",
            )
        )
    supervised.navigate_reviewed_greenhouse_form.assert_not_called()

    result = service.execute_form_action(
        GreenhouseFormActionApproval(
            **request.model_dump(),
            preview_fingerprint=preview.preview_fingerprint,
            confirmation_phrase=GREENHOUSE_FORM_NAVIGATION_CONFIRMATION,
        )
    )
    assert result is run
    supervised.navigate_reviewed_greenhouse_form.assert_called_once_with(
        run.id,
        form_review_fingerprint=request.form_review_fingerprint,
        control_key="next",
    )


def test_upload_action_derives_exact_selected_document_and_rejects_stale_preview(
    fixture: Fixture,
) -> None:
    _ready(fixture)
    selected = fixture.knowledge.get_version_record(fixture.version_id)
    assert selected is not None
    reviewed_document = selected.model_copy(update={"file_name": "candidate-resume.pdf"})
    knowledge = Mock()
    knowledge.get_version_record.return_value = reviewed_document
    supervised = Mock()
    run = _action_run(
        fixture,
        action=GreenhouseFormAction.REVIEW_DOCUMENT_UPLOAD,
        control_kind=BrowserControlKind.FILE_UPLOAD,
        ready=False,
    )
    supervised.get.return_value = run
    supervised.upload_reviewed_greenhouse_document.return_value = run
    service = GreenhouseApplicationService(fixture.service, supervised, knowledge)
    assert run.greenhouse_form is not None
    request = GreenhouseFormActionRequest(
        application_id=fixture.application_id,
        run_id=run.id,
        action=GreenhouseFormAction.REVIEW_DOCUMENT_UPLOAD,
        control_key="resume",
        form_review_fingerprint=run.greenhouse_form.review_fingerprint,
    )
    preview = service.preview_form_action(request)
    assert preview.selected_document_version_id == fixture.version_id
    assert preview.selected_document_file_name == "candidate-resume.pdf"
    assert preview.selected_document_sha256 == reviewed_document.sha256

    stale = GreenhouseFormActionApproval(
        **request.model_dump(),
        preview_fingerprint="0" * 64,
        confirmation_phrase=GREENHOUSE_FORM_UPLOAD_CONFIRMATION,
    )
    with pytest.raises(GreenhouseApplicationLaunchError, match="changed"):
        service.execute_form_action(stale)
    supervised.upload_reviewed_greenhouse_document.assert_not_called()

    result = service.execute_form_action(
        stale.model_copy(update={"preview_fingerprint": preview.preview_fingerprint})
    )
    assert result is run
    supervised.upload_reviewed_greenhouse_document.assert_called_once_with(
        run.id,
        form_review_fingerprint=request.form_review_fingerprint,
        control_key="resume",
        document=reviewed_document,
    )
