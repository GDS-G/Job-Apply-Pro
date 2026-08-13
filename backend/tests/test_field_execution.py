from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.domain.applications import (
    Application,
    ApplicationAnswerKind,
    ApplicationAnswerRecord,
    ApplicationAnswerSource,
    ApplicationAnswerStatus,
    ApplicationFieldBindingRecord,
    ApplicationFieldExecution,
    ApplicationFieldExecutionApproval,
    FieldAutomationPermission,
    FieldBindingSource,
    PortalFieldControlKind,
)
from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionKind,
    BrowserActionResult,
    BrowserControlKind,
    BrowserControlOption,
    BrowserEngine,
    BrowserObservation,
    BrowserObservedControl,
    BrowserPermission,
    BrowserSessionSnapshot,
    BrowserSessionState,
    BrowserTab,
    BrowserVerification,
    ConfirmationState,
    LocatorStrategy,
    SemanticLocator,
    VerificationKind,
)
from job_apply_pro.domain.portals import (
    PortalKind,
    SupervisedPortalDisposition,
    SupervisedPortalRunSnapshot,
    SupervisedPortalRunState,
)
from job_apply_pro.domain.workflow import WorkflowState
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.field_execution import (
    ApplicationFieldExecutionService,
    FieldExecutionConflictError,
    FieldExecutionPolicyError,
)
from job_apply_pro.storage.models import BrowserActionRow, BrowserSessionRow
from job_apply_pro.storage.repositories import BrowserRuntimeRepository

NOW = datetime(2026, 8, 12, tzinfo=UTC)
SECRET_ANSWER = "private-answer-value"


def _observation(
    control: BrowserObservedControl, fingerprint: str = "page-v1"
) -> BrowserObservation:
    return BrowserObservation(
        sequence=1,
        url="https://www.linkedin.com/jobs/apply",
        title="Apply",
        origin="https://www.linkedin.com",
        page_type="APPLICATION",
        page_fingerprint=fingerprint,
        tabs=[
            BrowserTab(
                index=0,
                url="https://www.linkedin.com/jobs/apply",
                title="Apply",
                active=True,
            )
        ],
        accessibility_snapshot="",
        visible_text="Email",
        controls=[control],
        validation_errors=[],
        modals=[],
        console_errors=[],
        network_failures=[],
        upload_status=[],
        download_status=[],
        screenshot_path="fixture.png",
        observed_at=NOW,
    )


class _ValueRepository:
    def __init__(self, value: object) -> None:
        self.value = value

    def get(self, _value_id: str) -> object:
        return self.value


class _AnswerRepository:
    def __init__(self, value: ApplicationAnswerRecord) -> None:
        self.value = value

    def get_application_answer(self, _answer_id: str) -> ApplicationAnswerRecord:
        return self.value


class _ExecutionRepository:
    def __init__(self) -> None:
        self.values: list[ApplicationFieldExecution] = []

    def add(self, execution: ApplicationFieldExecution) -> ApplicationFieldExecution:
        self.values.append(execution)
        return execution

    def list_for_application(self, application_id: str) -> list[ApplicationFieldExecution]:
        return [value for value in self.values if value.application_id == application_id]


class _SupervisedRepository(_ValueRepository):
    def save(self, run: SupervisedPortalRunSnapshot) -> SupervisedPortalRunSnapshot:
        self.value = run
        return run


class _Browser:
    def __init__(self, observation: BrowserObservation) -> None:
        self.observation = observation
        self.action: BrowserAction | None = None
        self.takeovers = 0

    def resume(self, session_id: str) -> BrowserSessionSnapshot:
        return BrowserSessionSnapshot(
            id=session_id,
            workflow_id="workflow-1",
            engine=BrowserEngine.CHROMIUM,
            profile_name="fixture",
            state=BrowserSessionState.ACTIVE,
            current_url=self.observation.url,
            allowed_origins=[self.observation.origin],
            observation=self.observation,
            action_count=0,
            created_at=NOW,
            updated_at=NOW,
        )

    def takeover(self, session_id: str) -> BrowserSessionSnapshot:
        self.takeovers += 1
        return self.resume(session_id).model_copy(
            update={"state": BrowserSessionState.USER_TAKEOVER}
        )

    def execute_action(self, session_id: str, action: BrowserAction) -> BrowserActionResult:
        self.action = action
        return BrowserActionResult(
            id="action-1",
            session_id=session_id,
            sequence=1,
            action=action,
            verified=True,
            attempts=1,
            observation=self.observation,
            created_at=NOW,
        )


def _fixture_service(
    *, enabled: bool = True, fingerprint: str = "page-v1"
) -> tuple[ApplicationFieldExecutionService, _Browser, _ExecutionRepository]:
    cipher = SensitiveDataCipher(StaticKeyProvider(b"k" * 32))
    answer = ApplicationAnswerRecord(
        id="answer-1",
        application_id="application-1",
        profile_id="profile-1",
        job_id="job-1",
        revision=2,
        encrypted_question=cipher.encrypt_bytes(
            b"Email", context="application-answer:answer-1:question"
        ),
        encrypted_normalized_question=None,
        canonical_field="email",
        answer_kind=ApplicationAnswerKind.EXACT,
        validation_rules={},
        encrypted_value=cipher.encrypt_bytes(
            SECRET_ANSWER.encode(), context="application-answer:answer-1:value"
        ),
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
    binding = ApplicationFieldBindingRecord(
        id="binding-1",
        application_id="application-1",
        application_answer_id=answer.id,
        answer_revision=answer.revision,
        portal=PortalKind.LINKEDIN.value,
        page_fingerprint="page-v1",
        control_key="email-control",
        control_kind=PortalFieldControlKind.EMAIL,
        encrypted_label="encrypted",
        encrypted_options="encrypted",
        required=True,
        canonical_field="email",
        confidence=1,
        binding_source=FieldBindingSource.USER_CONFIRMED,
        answer_source=answer.source_type,
        answer_kind=answer.answer_kind,
        validation_rules={},
        automation_permission=FieldAutomationPermission.AUTOFILL_ALLOWED,
        review_fingerprint="a" * 64,
        created_at=NOW,
        updated_at=NOW,
    )
    control = BrowserObservedControl(
        index=0,
        control_key="email-control",
        kind=BrowserControlKind.EMAIL,
        tag="input",
        input_type="email",
        field_name="email",
        label="Email",
        required=True,
        visible=True,
        locator=SemanticLocator(strategy=LocatorStrategy.LABEL, value="Email"),
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
        current_match=None,
        disposition=SupervisedPortalDisposition.USER_ACTION_REQUIRED,
        intervention_reasons=[],
        evidence=[],
        created_at=NOW,
        updated_at=NOW,
    )
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
    browser = _Browser(_observation(control, fingerprint))
    executions = _ExecutionRepository()
    service = ApplicationFieldExecutionService(
        bindings=_ValueRepository(binding),  # type: ignore[arg-type]
        binding_service=SimpleNamespace(
            preview=lambda _command: SimpleNamespace(compatible=True, review_fingerprint="a" * 64)
        ),  # type: ignore[arg-type]
        answers=_AnswerRepository(answer),
        applications=_ValueRepository(application),  # type: ignore[arg-type]
        executions=executions,
        supervised=_SupervisedRepository(run),  # type: ignore[arg-type]
        browser=browser,
        cipher=cipher,
        enabled=enabled,
    )
    return service, browser, executions


def test_executes_exact_approved_field_without_auditing_answer_text() -> None:
    service, browser, executions = _fixture_service()
    result = service.execute(
        "run-1",
        ApplicationFieldExecutionApproval(
            binding_id="binding-1",
            review_page_fingerprint="page-v1",
            confirmation_phrase="EXECUTE APPROVED FIELD",
        ),
    )

    assert result.verified
    assert result.action_fingerprint not in {SECRET_ANSWER, ""}
    assert SECRET_ANSWER not in result.model_dump_json()
    assert executions.values == [result]
    assert browser.action is not None
    assert browser.action.value == SECRET_ANSWER
    assert browser.action.sensitive_value
    assert browser.action.permission is BrowserPermission.ELEVATED
    assert browser.action.confirmation is ConfirmationState.CONFIRMED
    assert browser.takeovers == 1


def test_rejects_disabled_policy_and_stale_live_page() -> None:
    disabled, browser, _ = _fixture_service(enabled=False)
    approval = ApplicationFieldExecutionApproval(
        binding_id="binding-1",
        review_page_fingerprint="page-v1",
        confirmation_phrase="EXECUTE APPROVED FIELD",
    )
    with pytest.raises(FieldExecutionPolicyError, match="disabled"):
        disabled.execute("run-1", approval)
    assert browser.action is None

    stale, stale_browser, _ = _fixture_service(fingerprint="page-v2")
    with pytest.raises(FieldExecutionConflictError, match="changed"):
        stale.execute("run-1", approval)
    assert stale_browser.action is None
    assert stale_browser.takeovers == 1


def test_rejects_control_without_current_visibility_evidence() -> None:
    service, browser, _ = _fixture_service()
    assert browser.observation is not None
    browser.observation = browser.observation.model_copy(
        update={"controls": [browser.observation.controls[0].model_copy(update={"visible": False})]}
    )

    with pytest.raises(FieldExecutionPolicyError, match="Hidden fields"):
        service.execute(
            "run-1",
            ApplicationFieldExecutionApproval(
                binding_id="binding-1",
                review_page_fingerprint="page-v1",
                confirmation_phrase="EXECUTE APPROVED FIELD",
            ),
        )
    assert browser.action is None
    assert browser.takeovers == 1


def test_rejects_accessibly_disabled_control() -> None:
    service, browser, _ = _fixture_service()
    assert browser.observation is not None
    browser.observation = browser.observation.model_copy(
        update={
            "controls": [
                BrowserObservedControl.model_validate(
                    {
                        **browser.observation.controls[0].model_dump(),
                        "disabled": False,
                        "native_disabled": False,
                        "accessible_disabled": True,
                    }
                )
            ]
        }
    )

    with pytest.raises(FieldExecutionPolicyError, match="Disabled fields"):
        service.execute(
            "run-1",
            ApplicationFieldExecutionApproval(
                binding_id="binding-1",
                review_page_fingerprint="page-v1",
                confirmation_phrase="EXECUTE APPROVED FIELD",
            ),
        )
    assert browser.action is None
    assert browser.takeovers == 1


def test_rejects_inherited_disabled_control() -> None:
    service, browser, _ = _fixture_service()
    assert browser.observation is not None
    browser.observation = browser.observation.model_copy(
        update={
            "controls": [
                BrowserObservedControl.model_validate(
                    {
                        **browser.observation.controls[0].model_dump(),
                        "disabled": False,
                        "native_disabled": False,
                        "inherited_disabled": True,
                        "accessible_disabled": False,
                    }
                )
            ]
        }
    )

    with pytest.raises(FieldExecutionPolicyError, match="Disabled fields"):
        service.execute(
            "run-1",
            ApplicationFieldExecutionApproval(
                binding_id="binding-1",
                review_page_fingerprint="page-v1",
                confirmation_phrase="EXECUTE APPROVED FIELD",
            ),
        )
    assert browser.action is None
    assert browser.takeovers == 1


def test_rejects_accessibly_readonly_control() -> None:
    service, browser, _ = _fixture_service()
    assert browser.observation is not None
    browser.observation = browser.observation.model_copy(
        update={
            "controls": [
                BrowserObservedControl.model_validate(
                    {
                        **browser.observation.controls[0].model_dump(),
                        "read_only": False,
                        "native_read_only": False,
                        "accessible_read_only": True,
                    }
                )
            ]
        }
    )

    with pytest.raises(FieldExecutionPolicyError, match="Readonly fields"):
        service.execute(
            "run-1",
            ApplicationFieldExecutionApproval(
                binding_id="binding-1",
                review_page_fingerprint="page-v1",
                confirmation_phrase="EXECUTE APPROVED FIELD",
            ),
        )
    assert browser.action is None
    assert browser.takeovers == 1


def test_rejects_busy_control() -> None:
    service, browser, _ = _fixture_service()
    assert browser.observation is not None
    browser.observation = browser.observation.model_copy(
        update={
            "controls": [
                BrowserObservedControl.model_validate(
                    {
                        **browser.observation.controls[0].model_dump(),
                        "busy": False,
                        "control_busy": True,
                        "form_busy": False,
                    }
                )
            ]
        }
    )

    with pytest.raises(FieldExecutionPolicyError, match="Busy fields"):
        service.execute(
            "run-1",
            ApplicationFieldExecutionApproval(
                binding_id="binding-1",
                review_page_fingerprint="page-v1",
                confirmation_phrase="EXECUTE APPROVED FIELD",
            ),
        )
    assert browser.action is None
    assert browser.takeovers == 1


def test_rejects_inert_control() -> None:
    service, browser, _ = _fixture_service()
    assert browser.observation is not None
    browser.observation = browser.observation.model_copy(
        update={
            "controls": [
                BrowserObservedControl.model_validate(
                    {
                        **browser.observation.controls[0].model_dump(),
                        "inert": False,
                        "direct_inert": False,
                        "inherited_inert": True,
                    }
                )
            ]
        }
    )

    with pytest.raises(FieldExecutionPolicyError, match="Inert fields"):
        service.execute(
            "run-1",
            ApplicationFieldExecutionApproval(
                binding_id="binding-1",
                review_page_fingerprint="page-v1",
                confirmation_phrase="EXECUTE APPROVED FIELD",
            ),
        )
    assert browser.action is None
    assert browser.takeovers == 1


def test_rejects_accessibility_hidden_control() -> None:
    service, browser, _ = _fixture_service()
    assert browser.observation is not None
    browser.observation = browser.observation.model_copy(
        update={
            "controls": [
                BrowserObservedControl.model_validate(
                    {
                        **browser.observation.controls[0].model_dump(),
                        "accessibility_hidden": False,
                        "direct_accessibility_hidden": False,
                        "inherited_accessibility_hidden": True,
                    }
                )
            ]
        }
    )

    with pytest.raises(FieldExecutionPolicyError, match="Accessibility-hidden fields"):
        service.execute(
            "run-1",
            ApplicationFieldExecutionApproval(
                binding_id="binding-1",
                review_page_fingerprint="page-v1",
                confirmation_phrase="EXECUTE APPROVED FIELD",
            ),
        )
    assert browser.action is None
    assert browser.takeovers == 1


def test_rejects_repeated_control_without_provider_specific_locator() -> None:
    service, browser, _ = _fixture_service()
    assert browser.observation is not None
    browser.observation = browser.observation.model_copy(
        update={
            "controls": [
                BrowserObservedControl.model_validate(
                    {
                        **browser.observation.controls[0].model_dump(),
                        "repeat_group": "employment",
                        "repeat_index": 0,
                        "repeat_count": 2,
                    }
                )
            ]
        }
    )

    with pytest.raises(FieldExecutionPolicyError, match="Repeated fields"):
        service.execute(
            "run-1",
            ApplicationFieldExecutionApproval(
                binding_id="binding-1",
                review_page_fingerprint="page-v1",
                confirmation_phrase="EXECUTE APPROVED FIELD",
            ),
        )
    assert browser.action is None
    assert browser.takeovers == 1


def test_radio_group_uses_exact_visible_option_locator() -> None:
    control = BrowserObservedControl(
        index=0,
        control_key="arrangement-control",
        kind=BrowserControlKind.RADIO_GROUP,
        tag="input",
        input_type="radio",
        field_name="arrangement",
        group_label="Preferred work arrangement",
        visible=True,
        options=[
            BrowserControlOption(
                value="remote",
                label="Remote",
                locator=SemanticLocator(strategy=LocatorStrategy.LABEL, value="Remote"),
            ),
            BrowserControlOption(
                value="hybrid",
                label="Hybrid",
                locator=SemanticLocator(strategy=LocatorStrategy.LABEL, value="Hybrid"),
            ),
        ],
        locator=SemanticLocator(
            strategy=LocatorStrategy.LABEL,
            value="Preferred work arrangement",
        ),
    )

    action = ApplicationFieldExecutionService._action(control, "Remote")

    assert action.kind is BrowserActionKind.CHECK
    assert action.locator == SemanticLocator(
        strategy=LocatorStrategy.LABEL,
        value="Remote",
    )
    assert action.value is None
    assert action.verification.kind is VerificationKind.CHECKED_EQUALS
    assert action.verification.value == "true"
    with pytest.raises(FieldExecutionConflictError, match="exactly one"):
        ApplicationFieldExecutionService._action(control, "remote")
    ambiguous = control.model_copy(
        update={
            "options": [
                *control.options,
                BrowserControlOption(
                    value="remote-duplicate",
                    label="Remote",
                    locator=SemanticLocator(
                        strategy=LocatorStrategy.LABEL,
                        value="Remote",
                    ),
                ),
            ]
        }
    )
    with pytest.raises(FieldExecutionConflictError, match="exactly one"):
        ApplicationFieldExecutionService._action(ambiguous, "Remote")
    invalid_locator = control.model_copy(
        update={
            "options": [
                control.options[0].model_copy(update={"locator": None}),
                control.options[1],
            ]
        }
    )
    with pytest.raises(FieldExecutionPolicyError, match="exact visible-label"):
        ApplicationFieldExecutionService._validate_control(
            SimpleNamespace(control_kind=PortalFieldControlKind.RADIO_GROUP),  # type: ignore[arg-type]
            invalid_locator,
        )


def test_select_uses_unique_exact_visible_label() -> None:
    control = BrowserObservedControl(
        index=0,
        control_key="schedule-control",
        kind=BrowserControlKind.SELECT,
        tag="select",
        field_name="schedule",
        label="Preferred schedule",
        visible=True,
        options=[
            BrowserControlOption(value="schedule-internal-1", label="Day shift"),
            BrowserControlOption(value="schedule-internal-2", label="Night shift"),
        ],
        locator=SemanticLocator(
            strategy=LocatorStrategy.LABEL,
            value="Preferred schedule",
        ),
    )

    action = ApplicationFieldExecutionService._action(control, "Day shift")

    assert action.kind is BrowserActionKind.SELECT_LABEL
    assert action.value == "Day shift"
    assert action.verification.kind is VerificationKind.SELECTED_LABEL_EQUALS
    assert action.verification.value == "Day shift"
    with pytest.raises(FieldExecutionConflictError, match="visible select option"):
        ApplicationFieldExecutionService._action(control, "schedule-internal-1")
    with pytest.raises(FieldExecutionConflictError, match="visible select option"):
        ApplicationFieldExecutionService._action(control, "day shift")
    duplicate = control.model_copy(
        update={
            "options": [
                *control.options,
                BrowserControlOption(value="other", label="Day shift"),
            ]
        }
    )
    with pytest.raises(FieldExecutionConflictError, match="visible select option"):
        ApplicationFieldExecutionService._action(duplicate, "Day shift")


def test_sensitive_browser_action_is_redacted_before_persistence(session: Session) -> None:
    control = BrowserObservedControl(
        index=0,
        control_key="email-control",
        kind=BrowserControlKind.EMAIL,
        tag="input",
        input_type="email",
        label="Email",
        visible=True,
        locator=SemanticLocator(strategy=LocatorStrategy.LABEL, value="Email"),
    )
    locator = control.locator
    assert locator is not None
    action = BrowserAction(
        kind=BrowserActionKind.FILL,
        locator=locator,
        value=SECRET_ANSWER,
        intended_result="Populate approved field",
        verification=BrowserVerification(
            kind=VerificationKind.VALUE_EQUALS,
            locator=locator,
            value=SECRET_ANSWER,
        ),
        sensitive_value=True,
    )
    result = BrowserActionResult(
        id="action-1",
        session_id="session-1",
        sequence=1,
        action=action,
        verified=True,
        attempts=1,
        observation=_observation(control),
        created_at=NOW,
    )
    session.add(
        BrowserSessionRow(
            id="session-1",
            workflow_id="workflow-1",
            engine=BrowserEngine.CHROMIUM.value,
            profile_name="fixture",
            user_data_dir="fixture-profile",
            artifact_dir="fixture-artifacts",
            headless=True,
            state=BrowserSessionState.ACTIVE.value,
            current_url=result.observation.url,
            allowed_origins_json=[result.observation.origin],
            last_observation_json=result.observation.model_dump(mode="json"),
            trace_path=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.commit()
    BrowserRuntimeRepository(session).add_action(result)
    row = session.scalar(select(BrowserActionRow))
    assert row is not None
    assert SECRET_ANSWER not in str(row.action_json)
    action_json = cast(dict[str, object], row.action_json)
    assert action_json["value"] is None
    verification = cast(dict[str, object], action_json["verification"])
    assert verification["value"] is None
