from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from job_apply_pro.domain.applications import (
    Application,
    ApplicationAnswerKind,
    ApplicationAnswerRecord,
    ApplicationAnswerSource,
    ApplicationAnswerStatus,
    ApplicationFieldBindingRecord,
    ApplicationFieldCoverageStatus,
    ApplicationFieldExecution,
    FieldAutomationPermission,
    FieldBindingSource,
    PortalFieldControlKind,
)
from job_apply_pro.domain.browser import (
    BrowserControlKind,
    BrowserObservation,
    BrowserObservedControl,
    LocatorStrategy,
    SemanticLocator,
)
from job_apply_pro.domain.portals import (
    PortalKind,
    SupervisedPortalDisposition,
    SupervisedPortalRunSnapshot,
    SupervisedPortalRunState,
)
from job_apply_pro.domain.workflow import WorkflowState
from job_apply_pro.services.field_coverage import ApplicationFieldCoverageService
from job_apply_pro.services.greenhouse_form import GreenhouseFormContractService

NOW = datetime(2026, 8, 12, tzinfo=UTC)


class _Repository:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def get(self, value_id: str) -> Any | None:
        return next((value for value in self.values if value.id == value_id), None)

    def list_for_application(self, application_id: str) -> list[Any]:
        return [value for value in self.values if value.application_id == application_id]

    def get_application_answer(self, answer_id: str) -> Any | None:
        return self.get(answer_id)


def _answer(revision: int = 2) -> ApplicationAnswerRecord:
    return ApplicationAnswerRecord(
        id="answer-1",
        application_id="application-1",
        profile_id="profile-1",
        job_id="job-1",
        revision=revision,
        encrypted_question=None,
        encrypted_normalized_question=None,
        canonical_field="email",
        answer_kind=ApplicationAnswerKind.EXACT,
        validation_rules={},
        encrypted_value="not-read-by-coverage-review",
        status=ApplicationAnswerStatus.REVIEWED,
        source_type=ApplicationAnswerSource.USER_REVIEWED,
        source_answer_id=None,
        library_answer_id=None,
        evidence_claim_ids=[],
        retrieval_results=[],
        provider_id=None,
        model_id=None,
        prompt_version=None,
        policy_version="fixture",
        confidence=1,
        encrypted_generated_value=None,
        character_limit=20_000,
        character_limit_applied=False,
        limitations=[],
        user_edited=True,
        reuse_permission="APPLICATIONS",
        created_at=NOW,
        updated_at=NOW,
    )


def _binding(**changes: object) -> ApplicationFieldBindingRecord:
    values: dict[str, object] = {
        "id": "binding-1",
        "application_id": "application-1",
        "application_answer_id": "answer-1",
        "answer_revision": 2,
        "portal": PortalKind.LINKEDIN.value,
        "page_fingerprint": "page-v1",
        "control_key": "email-control",
        "control_kind": PortalFieldControlKind.EMAIL,
        "encrypted_label": "encrypted",
        "encrypted_options": "encrypted",
        "required": True,
        "canonical_field": "email",
        "confidence": 1,
        "binding_source": FieldBindingSource.USER_CONFIRMED,
        "answer_source": ApplicationAnswerSource.USER_REVIEWED,
        "answer_kind": ApplicationAnswerKind.EXACT,
        "validation_rules": {},
        "automation_permission": FieldAutomationPermission.AUTOFILL_ALLOWED,
        "review_fingerprint": "a" * 64,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return ApplicationFieldBindingRecord.model_validate(values)


def _execution() -> ApplicationFieldExecution:
    return ApplicationFieldExecution(
        id="execution-1",
        binding_id="binding-1",
        application_id="application-1",
        application_answer_id="answer-1",
        answer_revision=2,
        supervised_run_id="run-1",
        browser_session_id="session-1",
        portal=PortalKind.LINKEDIN.value,
        page_fingerprint_before="page-v1",
        page_fingerprint_after="page-v1",
        control_key="email-control",
        action_kind="FILL",
        verified=True,
        action_fingerprint="b" * 64,
        created_at=NOW,
    )


def _service(
    controls: list[BrowserObservedControl],
    *,
    bindings: list[ApplicationFieldBindingRecord] | None = None,
    answers: list[ApplicationAnswerRecord] | None = None,
    executions: list[ApplicationFieldExecution] | None = None,
    portal: PortalKind = PortalKind.LINKEDIN,
) -> ApplicationFieldCoverageService:
    application = Application(
        id="application-1",
        workflow_id="workflow-1",
        profile_id="profile-1",
        job_id="job-1",
        state=WorkflowState.DISCOVERED,
        selected_document_version_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
    current_url = (
        "https://job-boards.greenhouse.io/synthetic/jobs/100#app"
        if portal is PortalKind.GREENHOUSE
        else "https://www.linkedin.com/jobs/apply"
    )
    greenhouse_form = None
    if portal is PortalKind.GREENHOUSE:
        observation = BrowserObservation(
            sequence=1,
            url=current_url,
            title="Greenhouse application",
            origin="https://job-boards.greenhouse.io",
            page_type="APPLICATION_FORM",
            page_fingerprint="page-v1",
            tabs=[],
            accessibility_snapshot="",
            visible_text="Sanitized Greenhouse application",
            controls=controls,
            validation_errors=[],
            modals=[],
            console_errors=[],
            network_failures=[],
            upload_status=[],
            download_status=[],
            screenshot_path="fixture.png",
            observed_at=NOW,
        )
        greenhouse_form = GreenhouseFormContractService().assess(observation)
    run = SupervisedPortalRunSnapshot(
        id="run-1",
        portal=portal,
        workflow_id="workflow-1",
        browser_session_id="session-1",
        state=SupervisedPortalRunState.AWAITING_USER,
        current_url=current_url,
        allowed_origins=[current_url.split("/", 3)[0] + "//" + current_url.split("/", 3)[2]],
        page_fingerprint="page-v1",
        disposition=SupervisedPortalDisposition.USER_ACTION_REQUIRED,
        intervention_reasons=[],
        evidence=[],
        observed_controls=controls,
        greenhouse_form=greenhouse_form,
        created_at=NOW,
        updated_at=NOW,
    )
    return ApplicationFieldCoverageService(
        bindings=_Repository(bindings or []),
        answers=_Repository(answers or []),
        applications=_Repository([application]),
        executions=_Repository(executions or []),
        supervised=_Repository([run]),
    )


def _control(
    control_key: str,
    kind: BrowserControlKind = BrowserControlKind.EMAIL,
    **changes: object,
) -> BrowserObservedControl:
    input_type = {
        BrowserControlKind.EMAIL: "email",
        BrowserControlKind.TELEPHONE: "tel",
        BrowserControlKind.SIGNATURE: "signature",
    }.get(kind, "text")
    values: dict[str, object] = {
        "index": 0,
        "control_key": control_key,
        "kind": kind,
        "tag": "input",
        "input_type": input_type,
        "label": control_key.replace("-", " ").title(),
        "required": True,
        "visible": True,
        "locator": SemanticLocator(
            strategy=LocatorStrategy.LABEL,
            value=control_key.replace("-", " ").title(),
        ),
    }
    values.update(changes)
    return BrowserObservedControl.model_validate(values)


def _single_select_widget() -> BrowserObservedControl:
    return BrowserObservedControl.model_validate(
        {
            "index": 0,
            "control_key": "work-location",
            "tag": "input",
            "type": "text",
            "role": "combobox",
            "label": "Preferred work location",
            "required": True,
            "native_required": True,
            "visible": True,
            "widget_popup": "listbox",
            "widget_expanded": True,
            "widget_searchable": True,
            "widget_multiselectable": False,
            "widget_controls_one_visible_listbox": True,
            "options": [
                {"value": "remote-internal", "label": "Remote"},
                {"value": "hybrid-internal", "label": "Hybrid"},
            ],
        }
    )


def test_review_classifies_required_coverage_without_answer_values() -> None:
    controls = [
        _control("email-control"),
        _control("phone-control", BrowserControlKind.TELEPHONE),
        _control("signature-control", BrowserControlKind.SIGNATURE),
        _control("optional-control", required=False),
    ]
    review = _service(
        controls,
        bindings=[_binding()],
        answers=[_answer()],
    ).review("run-1", "application-1")

    assert review.required_control_count == 3
    assert review.satisfied_on_page_count == 0
    assert review.ready_to_execute_count == 1
    assert review.unbound_count == 1
    assert review.manual_required_count == 1
    assert [item.status for item in review.items] == [
        ApplicationFieldCoverageStatus.READY_TO_EXECUTE,
        ApplicationFieldCoverageStatus.UNBOUND,
        ApplicationFieldCoverageStatus.MANUAL_REQUIRED,
    ]
    assert "not-read-by-coverage-review" not in review.model_dump_json()


def test_review_maps_only_provider_reviewed_single_select_to_executable_kind() -> None:
    control = _single_select_widget()
    binding = _binding(
        portal=PortalKind.GREENHOUSE.value,
        control_key=control.control_key,
        control_kind=PortalFieldControlKind.SINGLE_SELECT_WIDGET,
    )

    greenhouse = _service(
        [control],
        bindings=[binding],
        answers=[_answer()],
        portal=PortalKind.GREENHOUSE,
    ).review("run-1", "application-1")
    linkedin = _service(
        [control],
        bindings=[binding.model_copy(update={"portal": PortalKind.LINKEDIN.value})],
        answers=[_answer()],
    ).review("run-1", "application-1")

    assert greenhouse.ready_to_execute_count == 1
    assert greenhouse.items[0].control_kind is PortalFieldControlKind.SINGLE_SELECT_WIDGET
    assert greenhouse.items[0].status is ApplicationFieldCoverageStatus.READY_TO_EXECUTE
    assert linkedin.manual_required_count == 1
    assert linkedin.items[0].control_kind is PortalFieldControlKind.CUSTOM
    assert linkedin.items[0].status is ApplicationFieldCoverageStatus.MANUAL_REQUIRED


def test_review_marks_verified_stale_and_ambiguous_bindings() -> None:
    control = _control("email-control")
    verified = _service(
        [control],
        bindings=[_binding()],
        answers=[_answer()],
        executions=[_execution()],
    ).review("run-1", "application-1")
    assert verified.items[0].status is ApplicationFieldCoverageStatus.ALREADY_VERIFIED

    stale = _service(
        [control],
        bindings=[_binding(page_fingerprint="page-old")],
        answers=[_answer()],
    ).review("run-1", "application-1")
    assert stale.items[0].status is ApplicationFieldCoverageStatus.STALE_BINDING

    ambiguous = _service(
        [control],
        bindings=[_binding(), _binding(id="binding-2")],
        answers=[_answer()],
    ).review("run-1", "application-1")
    assert ambiguous.items[0].status is ApplicationFieldCoverageStatus.AMBIGUOUS_BINDING


def test_review_rejects_cross_workflow_application() -> None:
    service = _service([])
    application = service._applications.get("application-1")
    assert application is not None
    service._applications = _Repository(
        [application.model_copy(update={"workflow_id": "another-workflow"})]
    )
    with pytest.raises(ValueError, match="another application workflow"):
        service.review("run-1", "application-1")


def test_review_requires_current_user_takeover_and_deterministic_locator() -> None:
    control = _control("email-control").model_copy(update={"locator": None})
    service = _service([control], bindings=[_binding()], answers=[_answer()])
    review = service.review("run-1", "application-1")
    assert review.items[0].status is ApplicationFieldCoverageStatus.MANUAL_REQUIRED

    run = service._supervised.get("run-1")
    assert run is not None
    service._supervised = _Repository(
        [run.model_copy(update={"state": SupervisedPortalRunState.STOPPED})]
    )
    with pytest.raises(ValueError, match="awaits the user"):
        service.review("run-1", "application-1")


def test_review_recognizes_native_constraint_validity_without_reading_value() -> None:
    control = _control(
        "email-control",
        will_validate=True,
        constraint_satisfied=True,
    )
    review = _service([control], bindings=[_binding()], answers=[_answer()]).review(
        "run-1", "application-1"
    )

    assert review.satisfied_on_page_count == 1
    assert review.ready_to_execute_count == 0
    assert review.items[0].status is ApplicationFieldCoverageStatus.SATISFIED_ON_PAGE
    assert "not-read-by-coverage-review" not in review.model_dump_json()


def test_review_ignores_legacy_or_hidden_required_controls() -> None:
    review = _service(
        [
            _control("visible-control"),
            _control("hidden-control", visible=False),
        ]
    ).review("run-1", "application-1")

    assert review.required_control_count == 1
    assert [item.control_key for item in review.items] == ["visible-control"]


def test_accessible_required_does_not_inherit_native_validity() -> None:
    control = _control(
        "accessible-control",
        required=True,
        native_required=False,
        accessible_required=True,
        will_validate=True,
        constraint_satisfied=True,
    )
    review = _service([control]).review("run-1", "application-1")

    assert review.required_control_count == 1
    assert review.satisfied_on_page_count == 0
    assert review.items[0].status is ApplicationFieldCoverageStatus.UNBOUND


def test_accessibly_disabled_required_control_remains_manual() -> None:
    control = _control(
        "accessible-disabled-control",
        disabled=False,
        native_disabled=False,
        accessible_disabled=True,
    )
    review = _service([control]).review("run-1", "application-1")

    assert control.disabled
    assert review.items[0].status is ApplicationFieldCoverageStatus.MANUAL_REQUIRED


def test_inherited_disabled_required_control_remains_manual() -> None:
    control = _control(
        "inherited-disabled-control",
        disabled=False,
        native_disabled=False,
        inherited_disabled=True,
        accessible_disabled=False,
    )
    review = _service([control]).review("run-1", "application-1")

    assert control.disabled
    assert control.native_disabled
    assert review.items[0].status is ApplicationFieldCoverageStatus.MANUAL_REQUIRED


def test_accessibly_readonly_required_control_remains_manual() -> None:
    control = _control(
        "accessible-readonly-control",
        read_only=False,
        native_read_only=False,
        accessible_read_only=True,
    )
    review = _service([control]).review("run-1", "application-1")

    assert control.read_only
    assert review.items[0].status is ApplicationFieldCoverageStatus.MANUAL_REQUIRED


def test_busy_required_control_remains_manual_despite_native_validity() -> None:
    control = _control(
        "busy-control",
        will_validate=True,
        constraint_satisfied=True,
        busy=False,
        control_busy=False,
        form_busy=True,
    )
    review = _service([control]).review("run-1", "application-1")

    assert control.busy
    assert review.satisfied_on_page_count == 0
    assert review.items[0].status is ApplicationFieldCoverageStatus.MANUAL_REQUIRED


def test_inert_required_control_remains_manual_despite_native_validity() -> None:
    control = _control(
        "inert-control",
        will_validate=True,
        constraint_satisfied=True,
        inert=False,
        direct_inert=False,
        inherited_inert=True,
    )
    review = _service([control]).review("run-1", "application-1")

    assert control.inert
    assert review.satisfied_on_page_count == 0
    assert review.items[0].status is ApplicationFieldCoverageStatus.MANUAL_REQUIRED


def test_accessibility_hidden_required_control_remains_manual_despite_native_validity() -> None:
    control = _control(
        "accessibility-hidden-control",
        will_validate=True,
        constraint_satisfied=True,
        accessibility_hidden=False,
        direct_accessibility_hidden=False,
        inherited_accessibility_hidden=True,
    )
    review = _service([control]).review("run-1", "application-1")

    assert control.accessibility_hidden
    assert review.satisfied_on_page_count == 0
    assert review.items[0].status is ApplicationFieldCoverageStatus.MANUAL_REQUIRED


def test_repeated_required_control_requires_provider_specific_locator() -> None:
    control = _control(
        "repeated-employer",
        repeat_group="employment",
        repeat_index=0,
        repeat_count=2,
    )
    review = _service([control], bindings=[_binding()], answers=[_answer()]).review(
        "run-1", "application-1"
    )

    assert review.items[0].status is ApplicationFieldCoverageStatus.MANUAL_REQUIRED
    assert "Repeated controls" in review.items[0].reason


def test_accessibly_invalid_control_does_not_inherit_native_validity() -> None:
    control = _control(
        "provider-invalid-control",
        will_validate=True,
        constraint_satisfied=True,
        accessible_invalid=True,
    )
    review = _service([control]).review("run-1", "application-1")

    assert review.satisfied_on_page_count == 0
    assert review.items[0].status is ApplicationFieldCoverageStatus.UNBOUND
