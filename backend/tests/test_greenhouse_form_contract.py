from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionKind,
    BrowserActionResult,
    BrowserObservation,
    BrowserObservedControl,
    BrowserPermission,
    BrowserTab,
    ConfirmationState,
)
from job_apply_pro.domain.greenhouse_form import (
    GreenhouseFormAction,
    GreenhouseFormStage,
    GreenhousePostconditionKind,
)
from job_apply_pro.services.greenhouse_form import (
    GREENHOUSE_FORM_POLICY_VERSION,
    GreenhouseFormContractError,
    GreenhouseFormContractService,
)


def _corpus() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "greenhouse_form_contracts_v1.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _observation(case: dict[str, Any]) -> BrowserObservation:
    url = str(case["url"])
    parsed = urlsplit(url)
    return BrowserObservation(
        sequence=1,
        url=url,
        title="Sanitized Greenhouse fixture",
        origin=f"{parsed.scheme}://{parsed.hostname}",
        page_type=str(case["page_type"]),
        page_fingerprint=str(case["page_fingerprint"]),
        tabs=[BrowserTab(index=0, url=url, title="Sanitized fixture", active=True)],
        accessibility_snapshot="",
        visible_text="Sanitized Greenhouse application fixture",
        controls=[BrowserObservedControl.model_validate(item) for item in case.get("controls", [])],
        validation_errors=[str(value) for value in case.get("validation_errors", [])],
        modals=[],
        console_errors=[],
        network_failures=[],
        upload_status=[str(value) for value in case.get("upload_status", [])],
        download_status=[],
        screenshot_path=f"C:/sanitized/{case['id']}.png",
        observed_at=datetime.now(UTC),
    )


def _cases() -> dict[str, dict[str, Any]]:
    corpus = _corpus()
    assert corpus["version"] == GREENHOUSE_FORM_POLICY_VERSION
    assert corpus["sanitized"] is True
    cases = corpus["cases"]
    assert isinstance(cases, list)
    return {str(case["id"]): case for case in cases if isinstance(case, dict)}


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
            "aria-haspopup": "listbox",
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


def _result(
    before: BrowserObservation,
    after: BrowserObservation,
    *,
    control_key: str,
    action_kind: BrowserActionKind,
    file_path: str | None = None,
    verified: bool = True,
) -> BrowserActionResult:
    control = next(item for item in before.controls if item.control_key == control_key)
    return BrowserActionResult(
        id=str(uuid4()),
        session_id="sanitized-session",
        sequence=1,
        action=BrowserAction(
            kind=action_kind,
            locator=control.locator,
            file_path=file_path,
            intended_result="Exercise one sanitized Greenhouse postcondition",
            permission=BrowserPermission.ELEVATED,
            confirmation=ConfirmationState.CONFIRMED,
        ),
        verified=verified,
        attempts=1,
        observation=after,
        created_at=datetime.now(UTC),
    )


def test_sanitized_greenhouse_form_corpus_exercises_every_stage_and_boundary() -> None:
    service = GreenhouseFormContractService()
    cases = _cases()
    observed_stages = set()
    for case in cases.values():
        assessment = service.assess(_observation(case))
        expected = case["expected"]
        assert isinstance(expected, dict)
        assert assessment.stage.value == expected["stage"]
        assert assessment.required_control_count == expected["required"]
        assert assessment.satisfied_required_count == expected["satisfied"]
        assert assessment.review_field_count == expected["review_fields"]
        assert assessment.upload_review_count == expected["upload_reviews"]
        assert assessment.manual_intervention_count == expected["manual"]
        assert assessment.ready_to_advance is expected["ready"]
        assert assessment.navigation_control_key == expected["navigation"]
        assert len(assessment.review_fingerprint) == 64
        observed_stages.add(assessment.stage)

    assert observed_stages == set(GreenhouseFormStage)
    blocked = service.assess(_observation(cases["contact-blocked-by-field-and-widget"]))
    assert {item.action for item in blocked.controls} >= {
        GreenhouseFormAction.REVIEW_FIELD,
        GreenhouseFormAction.USER_INTERVENTION,
        GreenhouseFormAction.REVIEW_NAVIGATION,
    }
    assert (
        next(
            item for item in blocked.controls if item.control_key == "location-widget"
        ).postcondition
        is GreenhousePostconditionKind.USER_VERIFIED
    )
    review = service.assess(_observation(cases["submission-review"]))
    assert review.controls[0].action is GreenhouseFormAction.FINAL_SUBMISSION_GATE


def test_expanded_greenhouse_single_select_is_a_reviewed_field() -> None:
    service = GreenhouseFormContractService()
    observation = _observation(_cases()["contact-ready"]).model_copy(
        update={"controls": [_single_select_widget()]}
    )

    assessment = service.assess(observation)

    assert assessment.review_field_count == 1
    assert assessment.manual_intervention_count == 0
    assert assessment.controls[0].action is GreenhouseFormAction.REVIEW_FIELD
    assert assessment.controls[0].postcondition is GreenhousePostconditionKind.VALUE_EQUALS


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("widget_expanded", False),
        ("widget_multiselectable", True),
        ("widget_popup", "menu"),
        ("widget_searchable", False),
        ("widget_controls_one_visible_listbox", False),
        ("repeat_count", 2),
        ("locator", None),
        ("options", []),
    ],
    ids=[
        "collapsed",
        "multiselect",
        "non-listbox",
        "non-searchable",
        "unowned-or-hidden-listbox",
        "repeated",
        "unlocatable",
        "no-options",
    ],
)
def test_unbounded_greenhouse_widgets_remain_manual(field: str, value: object) -> None:
    service = GreenhouseFormContractService()
    unsafe = _single_select_widget().model_copy(update={field: value})
    observation = _observation(_cases()["contact-ready"]).model_copy(update={"controls": [unsafe]})

    assessment = service.assess(observation)

    assert assessment.review_field_count == 0
    assert assessment.manual_intervention_count == 1
    assert assessment.controls[0].action is GreenhouseFormAction.USER_INTERVENTION


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("visible", False),
        ("disabled", True),
        ("busy", True),
        ("inert", True),
        ("accessibility_hidden", True),
        ("repeat_count", 2),
        ("locator", None),
    ],
    ids=["hidden", "disabled", "busy", "inert", "accessibility-hidden", "repeated", "unlocatable"],
)
def test_final_submit_contract_refuses_unsafe_controls(field: str, value: object) -> None:
    service = GreenhouseFormContractService()
    observation = _observation(_cases()["submission-review"])
    unsafe = observation.controls[0].model_copy(update={field: value})

    assessment = service.assess(observation.model_copy(update={"controls": [unsafe]}))

    assert not any(
        item.action is GreenhouseFormAction.FINAL_SUBMISSION_GATE for item in assessment.controls
    )


def test_navigation_postcondition_requires_current_ready_review_and_later_stage() -> None:
    service = GreenhouseFormContractService()
    cases = _cases()
    before = _observation(cases["contact-ready"])
    after = _observation(cases["document-upload-pending"])
    assessment = service.assess(before)
    result = _result(
        before,
        after,
        control_key="contact-next",
        action_kind=BrowserActionKind.CLICK,
    )

    verified = service.verify_navigation(
        before,
        result,
        expected_review_fingerprint=assessment.review_fingerprint,
    )
    assert verified.verified
    assert verified.kind is GreenhousePostconditionKind.NEXT_STAGE_OBSERVED

    stale = service.verify_navigation(
        before,
        result,
        expected_review_fingerprint="0" * 64,
    )
    assert not stale.verified
    assert "changed" in stale.reason

    same_page = result.model_copy(update={"observation": before})
    refused = service.verify_navigation(
        before,
        same_page,
        expected_review_fingerprint=assessment.review_fingerprint,
    )
    assert not refused.verified
    assert "fingerprint" in refused.reason
    assert "later" in refused.reason

    escaped_case = dict(cases["document-upload-pending"])
    escaped_case["url"] = "https://example.test/application"
    escaped = result.model_copy(update={"observation": _observation(escaped_case)})
    escaped_evidence = service.verify_navigation(
        before,
        escaped,
        expected_review_fingerprint=assessment.review_fingerprint,
    )
    assert not escaped_evidence.verified
    assert "exact Greenhouse origin" in escaped_evidence.reason

    confirmation = result.model_copy(
        update={"observation": _observation(cases["identifier-backed-confirmation"])}
    )
    confirmation_evidence = service.verify_navigation(
        before,
        confirmation,
        expected_review_fingerprint=assessment.review_fingerprint,
    )
    assert not confirmation_evidence.verified
    assert "cannot establish final application confirmation" in confirmation_evidence.reason


def test_upload_postcondition_requires_exact_control_origin_and_observed_filename() -> None:
    service = GreenhouseFormContractService()
    cases = _cases()
    before = _observation(cases["document-upload-pending"])
    after = _observation(cases["document-upload-ready"])
    result = _result(
        before,
        after,
        control_key="resume",
        action_kind=BrowserActionKind.UPLOAD,
        file_path="C:/staged/candidate-resume.pdf",
    )

    verified = service.verify_upload(
        before,
        result,
        control_key="resume",
        expected_file_name="candidate-resume.pdf",
    )
    assert verified.verified
    assert verified.kind is GreenhousePostconditionKind.UPLOAD_FILE_NAME_OBSERVED

    wrong_name = service.verify_upload(
        before,
        result,
        control_key="resume",
        expected_file_name="different-resume.pdf",
    )
    assert not wrong_name.verified
    assert "not observed once" in wrong_name.reason

    wrong_action_file = result.model_copy(
        update={
            "action": result.action.model_copy(
                update={"file_path": "C:/staged/different-resume.pdf"}
            )
        }
    )
    wrong_action = service.verify_upload(
        before,
        wrong_action_file,
        control_key="resume",
        expected_file_name="candidate-resume.pdf",
    )
    assert not wrong_action.verified
    assert "exact reviewed staged" in wrong_action.reason

    already_present = service.verify_upload(
        before.model_copy(update={"upload_status": ["candidate-resume.pdf"]}),
        result,
        control_key="resume",
        expected_file_name="candidate-resume.pdf",
    )
    assert not already_present.verified
    assert "already present" in already_present.reason

    unsafe_name = service.verify_upload(
        before,
        result,
        control_key="resume",
        expected_file_name="../candidate-resume.pdf",
    )
    assert not unsafe_name.verified
    assert "bounded supported" in unsafe_name.reason


def test_greenhouse_form_contract_rejects_other_origins_and_unknown_page_types() -> None:
    service = GreenhouseFormContractService()
    case = _cases()["contact-ready"]
    foreign = dict(case)
    foreign["url"] = "https://example.test/application"
    with pytest.raises(GreenhouseFormContractError, match="allowed Greenhouse"):
        service.assess(_observation(foreign))

    unknown = dict(case)
    unknown["page_type"] = "UNKNOWN"
    with pytest.raises(GreenhouseFormContractError, match="does not recognize"):
        service.assess(_observation(unknown))
