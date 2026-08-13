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
    run = SupervisedPortalRunSnapshot(
        id="run-1",
        portal=PortalKind.LINKEDIN,
        workflow_id="workflow-1",
        browser_session_id="session-1",
        state=SupervisedPortalRunState.AWAITING_USER,
        current_url="https://www.linkedin.com/jobs/apply",
        allowed_origins=["https://www.linkedin.com"],
        page_fingerprint="page-v1",
        disposition=SupervisedPortalDisposition.USER_ACTION_REQUIRED,
        intervention_reasons=[],
        evidence=[],
        observed_controls=controls,
        created_at=NOW,
        updated_at=NOW,
    )
    return ApplicationFieldCoverageService(
        bindings=_Repository(bindings or []),  # type: ignore[arg-type]
        answers=_Repository(answers or []),  # type: ignore[arg-type]
        applications=_Repository([application]),  # type: ignore[arg-type]
        executions=_Repository(executions or []),  # type: ignore[arg-type]
        supervised=_Repository([run]),  # type: ignore[arg-type]
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
    service._applications = _Repository(  # type: ignore[assignment]
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
    service._supervised = _Repository(  # type: ignore[assignment]
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
