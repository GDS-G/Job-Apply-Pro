from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from job_apply_pro.domain.applications import (
    Application,
    ApplicationAnswerRecord,
    ApplicationFieldBindingPreview,
    ApplicationFieldBindingPreviewRequest,
    ApplicationFieldBindingRecord,
    ApplicationFieldExecution,
    ApplicationFieldExecutionApproval,
    FieldAutomationPermission,
    ObservedPortalField,
    PortalFieldControlKind,
)
from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionKind,
    BrowserActionResult,
    BrowserControlKind,
    BrowserObservedControl,
    BrowserPermission,
    BrowserSessionSnapshot,
    BrowserVerification,
    ConfirmationState,
    LocatorStrategy,
    SemanticLocator,
    VerificationKind,
)
from job_apply_pro.domain.portals import (
    SupervisedPortalRunSnapshot,
    SupervisedPortalRunState,
)
from job_apply_pro.security.encryption import SensitiveDataCipher


class FieldExecutionError(RuntimeError):
    pass


class FieldExecutionPolicyError(FieldExecutionError):
    pass


class FieldExecutionConflictError(FieldExecutionError):
    pass


class BindingRepositoryProtocol(Protocol):
    def get(self, binding_id: str) -> ApplicationFieldBindingRecord | None: ...


class BindingServiceProtocol(Protocol):
    def preview(
        self, command: ApplicationFieldBindingPreviewRequest
    ) -> ApplicationFieldBindingPreview: ...


class AnswerRepositoryProtocol(Protocol):
    def get_application_answer(self, answer_id: str) -> ApplicationAnswerRecord | None: ...


class ApplicationRepositoryProtocol(Protocol):
    def get(self, application_id: str) -> Application | None: ...


class ExecutionRepositoryProtocol(Protocol):
    def add(self, execution: ApplicationFieldExecution) -> ApplicationFieldExecution: ...

    def list_for_application(self, application_id: str) -> list[ApplicationFieldExecution]: ...


class SupervisedRepositoryProtocol(Protocol):
    def get(self, run_id: str) -> SupervisedPortalRunSnapshot | None: ...


class BrowserProtocol(Protocol):
    def resume(self, session_id: str) -> BrowserSessionSnapshot: ...

    def takeover(self, session_id: str) -> BrowserSessionSnapshot: ...

    def execute_action(self, session_id: str, action: BrowserAction) -> BrowserActionResult: ...


_SUPPORTED_CONTROL_KINDS = {
    BrowserControlKind.TEXT,
    BrowserControlKind.TEXT_AREA,
    BrowserControlKind.EMAIL,
    BrowserControlKind.TELEPHONE,
    BrowserControlKind.NUMBER,
    BrowserControlKind.DATE,
    BrowserControlKind.SELECT,
    BrowserControlKind.RADIO_GROUP,
    BrowserControlKind.CHECKBOX,
}


class ApplicationFieldExecutionService:
    def __init__(
        self,
        *,
        bindings: BindingRepositoryProtocol,
        binding_service: BindingServiceProtocol,
        answers: AnswerRepositoryProtocol,
        applications: ApplicationRepositoryProtocol,
        executions: ExecutionRepositoryProtocol,
        supervised: SupervisedRepositoryProtocol,
        browser: BrowserProtocol,
        cipher: SensitiveDataCipher,
        enabled: bool,
    ) -> None:
        self._bindings = bindings
        self._binding_service = binding_service
        self._answers = answers
        self._applications = applications
        self._executions = executions
        self._supervised = supervised
        self._browser = browser
        self._cipher = cipher
        self._enabled = enabled

    def execute(
        self, run_id: str, approval: ApplicationFieldExecutionApproval
    ) -> ApplicationFieldExecution:
        if not self._enabled:
            raise FieldExecutionPolicyError("Supervised field execution is disabled")
        if approval.confirmation_phrase != "EXECUTE APPROVED FIELD":
            raise FieldExecutionPolicyError("Field execution confirmation phrase is invalid")

        binding = self._bindings.get(approval.binding_id)
        if binding is None:
            raise LookupError(f"Application field binding {approval.binding_id} was not found")
        if binding.automation_permission is not FieldAutomationPermission.AUTOFILL_ALLOWED:
            raise FieldExecutionPolicyError("This field binding is not approved for autofill")

        run = self._supervised.get(run_id)
        if run is None:
            raise LookupError(f"Supervised portal run {run_id} was not found")
        if run.state is not SupervisedPortalRunState.AWAITING_USER:
            raise FieldExecutionPolicyError(
                "Fields can only be executed while the supervised run awaits the user"
            )
        if approval.review_page_fingerprint != run.page_fingerprint:
            raise FieldExecutionConflictError(
                "Portal page changed after review; capture and review the field again"
            )
        if binding.page_fingerprint != run.page_fingerprint:
            raise FieldExecutionConflictError("Approved field binding belongs to another page")
        if binding.portal != run.portal.value:
            raise FieldExecutionConflictError("Approved field binding belongs to another portal")

        application = self._applications.get(binding.application_id)
        if application is None:
            raise LookupError(f"Application {binding.application_id} was not found")
        if application.workflow_id != run.workflow_id:
            raise FieldExecutionConflictError("Portal run belongs to another application workflow")

        answer = self._answers.get_application_answer(binding.application_answer_id)
        if answer is None:
            raise LookupError(f"Application answer {binding.application_answer_id} was not found")
        if answer.application_id != application.id or answer.revision != binding.answer_revision:
            raise FieldExecutionConflictError(
                "Reviewed answer changed after binding; approve the field again"
            )

        resumed = False
        try:
            session = self._browser.resume(run.browser_session_id)
            resumed = True
            observation = session.observation
            if observation is None:
                raise FieldExecutionConflictError("Browser did not produce a live observation")
            if observation.page_fingerprint != run.page_fingerprint:
                raise FieldExecutionConflictError(
                    "Portal page changed after review; capture and review the field again"
                )
            controls = [
                control
                for control in observation.controls
                if control.control_key == binding.control_key
            ]
            if len(controls) != 1:
                raise FieldExecutionConflictError(
                    "Approved field is missing or ambiguous on the current page"
                )
            control = controls[0]
            self._validate_control(binding, control)
            field = self._observed_field(run, control)
            preview = self._binding_service.preview(
                ApplicationFieldBindingPreviewRequest(
                    application_answer_id=answer.id,
                    observed_field=field,
                )
            )
            if not preview.compatible or preview.review_fingerprint != binding.review_fingerprint:
                raise FieldExecutionConflictError(
                    "Observed field or reviewed answer changed; approve the binding again"
                )

            answer_value = self._cipher.decrypt_bytes(
                answer.encrypted_value,
                context=f"application-answer:{answer.id}:value",
            ).decode()
            action = self._action(control, answer_value)
            result = self._browser.execute_action(run.browser_session_id, action)
            execution = self._execution(binding, run, result)
            self._executions.add(execution)
            return execution
        finally:
            if resumed:
                self._browser.takeover(run.browser_session_id)

    def list_for_application(self, application_id: str) -> list[ApplicationFieldExecution]:
        return self._executions.list_for_application(application_id)

    @staticmethod
    def _validate_control(
        binding: ApplicationFieldBindingRecord, control: BrowserObservedControl
    ) -> None:
        if control.kind not in _SUPPORTED_CONTROL_KINDS:
            raise FieldExecutionPolicyError(
                f"{control.kind.value} controls require visible user handling"
            )
        if control.locator is None:
            raise FieldExecutionPolicyError("Field has no deterministic semantic locator")
        if control.disabled:
            raise FieldExecutionPolicyError("Disabled fields cannot be executed")
        if not control.visible:
            raise FieldExecutionPolicyError("Hidden fields cannot be executed")
        if control.legal_attestation:
            raise FieldExecutionPolicyError("Legal attestations require visible user handling")
        if control.kind.value != binding.control_kind.value:
            raise FieldExecutionConflictError("Observed control kind changed after binding")
        if control.kind is BrowserControlKind.RADIO_GROUP and any(
            option.locator
            not in {
                SemanticLocator(
                    strategy=LocatorStrategy.LABEL,
                    value=option.label,
                    exact=True,
                ),
                SemanticLocator(
                    strategy=LocatorStrategy.ROLE,
                    value="radio",
                    name=option.label,
                    exact=True,
                ),
            }
            for option in control.options
        ):
            raise FieldExecutionPolicyError("Radio options require exact visible-label locators")

    @staticmethod
    def _observed_field(
        run: SupervisedPortalRunSnapshot, control: BrowserObservedControl
    ) -> ObservedPortalField:
        return ObservedPortalField(
            portal=run.portal.value,
            page_fingerprint=run.page_fingerprint,
            control_key=control.control_key,
            control_kind=PortalFieldControlKind(control.kind.value),
            label=(
                control.label
                or control.group_label
                or control.field_name
                or "Observed " + control.kind.value.casefold() + " control"
            ),
            required=control.required,
            options=[option.label for option in control.options],
            character_limit=control.character_limit,
            minimum_number=control.minimum_number,
            maximum_number=control.maximum_number,
            earliest_date=control.earliest_date,
            latest_date=control.latest_date,
            legal_attestation=control.legal_attestation,
        )

    @staticmethod
    def _action(control: BrowserObservedControl, answer_value: str) -> BrowserAction:
        locator = control.locator
        if locator is None:  # pragma: no cover - validated before construction
            raise FieldExecutionPolicyError("Field has no deterministic semantic locator")
        if control.kind is BrowserControlKind.RADIO_GROUP:
            matches = [option for option in control.options if answer_value == option.label]
            if len(matches) != 1 or matches[0].locator is None:
                raise FieldExecutionConflictError(
                    "Reviewed answer does not identify exactly one locatable radio option"
                )
            locator = matches[0].locator
            value = None
            kind = BrowserActionKind.CHECK
            verification = BrowserVerification(
                kind=VerificationKind.CHECKED_EQUALS,
                locator=locator,
                value="true",
            )
        elif control.kind is BrowserControlKind.SELECT:
            matches = [option for option in control.options if answer_value == option.label]
            if len(matches) != 1:
                raise FieldExecutionConflictError(
                    "Reviewed answer does not identify exactly one visible select option"
                )
            value = matches[0].label
            kind = BrowserActionKind.SELECT_LABEL
            verification = BrowserVerification(
                kind=VerificationKind.SELECTED_LABEL_EQUALS, locator=locator, value=value
            )
        elif control.kind is BrowserControlKind.CHECKBOX:
            normalized = answer_value.strip().casefold()
            if normalized in {"yes", "true", "1", "checked"}:
                checked = True
            elif normalized in {"no", "false", "0", "unchecked"}:
                checked = False
            else:
                raise FieldExecutionConflictError(
                    "Reviewed checkbox answer must explicitly mean yes or no"
                )
            kind = BrowserActionKind.CHECK if checked else BrowserActionKind.UNCHECK
            value = None
            verification = BrowserVerification(
                kind=VerificationKind.CHECKED_EQUALS,
                locator=locator,
                value="true" if checked else "false",
            )
        else:
            kind = BrowserActionKind.FILL
            value = answer_value
            verification = BrowserVerification(
                kind=VerificationKind.VALUE_EQUALS,
                locator=locator,
                value=answer_value,
            )
        return BrowserAction(
            kind=kind,
            locator=locator,
            value=value,
            preconditions=[
                BrowserVerification(kind=VerificationKind.LOCATOR_VISIBLE, locator=locator)
            ],
            intended_result="Populate one explicitly approved application field",
            verification=verification,
            permission=BrowserPermission.ELEVATED,
            confirmation=ConfirmationState.CONFIRMED,
            sensitive_value=True,
        )

    @staticmethod
    def _execution(
        binding: ApplicationFieldBindingRecord,
        run: SupervisedPortalRunSnapshot,
        result: BrowserActionResult,
    ) -> ApplicationFieldExecution:
        payload = {
            "binding_id": binding.id,
            "application_id": binding.application_id,
            "answer_id": binding.application_answer_id,
            "answer_revision": binding.answer_revision,
            "run_id": run.id,
            "browser_session_id": run.browser_session_id,
            "portal": run.portal.value,
            "before": run.page_fingerprint,
            "after": result.observation.page_fingerprint,
            "control_key": binding.control_key,
            "action_kind": result.action.kind.value,
            "verified": result.verified,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ApplicationFieldExecution(
            id=str(uuid4()),
            binding_id=binding.id,
            application_id=binding.application_id,
            application_answer_id=binding.application_answer_id,
            answer_revision=binding.answer_revision,
            supervised_run_id=run.id,
            browser_session_id=run.browser_session_id,
            portal=run.portal.value,
            page_fingerprint_before=run.page_fingerprint,
            page_fingerprint_after=result.observation.page_fingerprint,
            control_key=binding.control_key,
            action_kind=result.action.kind.value,
            verified=result.verified,
            action_fingerprint=fingerprint,
            error=(
                "Sensitive browser action failed or could not be verified" if result.error else None
            ),
            created_at=datetime.now(UTC),
        )
