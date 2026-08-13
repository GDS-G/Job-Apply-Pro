from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Protocol

from job_apply_pro.domain.applications import (
    Application,
    ApplicationAnswerRecord,
    ApplicationFieldBindingRecord,
    ApplicationFieldCoverageItem,
    ApplicationFieldCoverageReview,
    ApplicationFieldCoverageStatus,
    ApplicationFieldExecution,
    FieldAutomationPermission,
    PortalFieldControlKind,
)
from job_apply_pro.domain.browser import (
    BrowserControlKind,
    BrowserObservedControl,
    LocatorStrategy,
    SemanticLocator,
)
from job_apply_pro.domain.portals import SupervisedPortalRunSnapshot, SupervisedPortalRunState


class BindingRepositoryProtocol(Protocol):
    def list_for_application(self, application_id: str) -> list[ApplicationFieldBindingRecord]: ...


class AnswerRepositoryProtocol(Protocol):
    def get_application_answer(self, answer_id: str) -> ApplicationAnswerRecord | None: ...


class ApplicationRepositoryProtocol(Protocol):
    def get(self, application_id: str) -> Application | None: ...


class ExecutionRepositoryProtocol(Protocol):
    def list_for_application(self, application_id: str) -> list[ApplicationFieldExecution]: ...


class SupervisedRepositoryProtocol(Protocol):
    def get(self, run_id: str) -> SupervisedPortalRunSnapshot | None: ...


_EXECUTABLE_KINDS = {
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
_PORTAL_FIELD_KINDS = {kind.value for kind in PortalFieldControlKind}


class ApplicationFieldCoverageService:
    """Classify required controls using metadata only; never decrypt or execute answers."""

    def __init__(
        self,
        *,
        bindings: BindingRepositoryProtocol,
        answers: AnswerRepositoryProtocol,
        applications: ApplicationRepositoryProtocol,
        executions: ExecutionRepositoryProtocol,
        supervised: SupervisedRepositoryProtocol,
    ) -> None:
        self._bindings = bindings
        self._answers = answers
        self._applications = applications
        self._executions = executions
        self._supervised = supervised

    def review(self, run_id: str, application_id: str) -> ApplicationFieldCoverageReview:
        run = self._supervised.get(run_id)
        if run is None:
            raise LookupError(f"Supervised portal run {run_id} was not found")
        application = self._applications.get(application_id)
        if application is None:
            raise LookupError(f"Application {application_id} was not found")
        if application.workflow_id != run.workflow_id:
            raise ValueError("Portal run belongs to another application workflow")
        if run.state is not SupervisedPortalRunState.AWAITING_USER:
            raise ValueError(
                "Required-field coverage is current only while the supervised run awaits the user"
            )

        bindings = self._bindings.list_for_application(application_id)
        executions = self._executions.list_for_application(application_id)
        items = [
            self._classify(control, run, bindings, executions)
            for control in run.observed_controls
            if control.required and control.visible
        ]
        items.sort(key=lambda item: (item.label.casefold(), item.control_key))
        counts = Counter(item.status for item in items)
        fingerprint_payload = {
            "application_id": application_id,
            "run_id": run.id,
            "portal": run.portal.value,
            "page_fingerprint": run.page_fingerprint,
            "items": [item.model_dump(mode="json") for item in items],
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ApplicationFieldCoverageReview(
            application_id=application_id,
            supervised_run_id=run.id,
            portal=run.portal.value,
            page_fingerprint=run.page_fingerprint,
            required_control_count=len(items),
            satisfied_on_page_count=counts[ApplicationFieldCoverageStatus.SATISFIED_ON_PAGE],
            ready_to_execute_count=counts[ApplicationFieldCoverageStatus.READY_TO_EXECUTE],
            already_verified_count=counts[ApplicationFieldCoverageStatus.ALREADY_VERIFIED],
            manual_required_count=counts[ApplicationFieldCoverageStatus.MANUAL_REQUIRED],
            unbound_count=counts[ApplicationFieldCoverageStatus.UNBOUND],
            stale_binding_count=counts[ApplicationFieldCoverageStatus.STALE_BINDING],
            ambiguous_binding_count=counts[ApplicationFieldCoverageStatus.AMBIGUOUS_BINDING],
            items=items,
            review_fingerprint=fingerprint,
        )

    def _classify(
        self,
        control: BrowserObservedControl,
        run: SupervisedPortalRunSnapshot,
        bindings: list[ApplicationFieldBindingRecord],
        executions: list[ApplicationFieldExecution],
    ) -> ApplicationFieldCoverageItem:
        label = control.label or control.group_label or control.field_name or control.kind.value
        kind = (
            PortalFieldControlKind(control.kind.value)
            if control.kind.value in _PORTAL_FIELD_KINDS
            else PortalFieldControlKind.CUSTOM
        )
        relevant = [binding for binding in bindings if binding.control_key == control.control_key]
        current = [
            binding
            for binding in relevant
            if binding.page_fingerprint == run.page_fingerprint
            and binding.portal == run.portal.value
            and binding.control_kind == kind
        ]
        if control.kind not in _EXECUTABLE_KINDS or control.legal_attestation or control.disabled:
            return self._item(
                control,
                label,
                kind,
                ApplicationFieldCoverageStatus.MANUAL_REQUIRED,
                None,
                "This required control must remain under visible user handling.",
            )
        if (
            control.native_required
            and control.will_validate
            and control.constraint_satisfied
            and not control.accessible_invalid
        ):
            return self._item(
                control,
                label,
                kind,
                ApplicationFieldCoverageStatus.SATISFIED_ON_PAGE,
                current[0].id if len(current) == 1 else None,
                "The current page reports this required native control as constraint-valid; "
                "its value remains private and semantic correctness still requires review.",
            )
        if control.locator is None or (
            control.kind is BrowserControlKind.RADIO_GROUP
            and any(
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
            )
        ):
            return self._item(
                control,
                label,
                kind,
                ApplicationFieldCoverageStatus.MANUAL_REQUIRED,
                None,
                "This required control has no deterministic executable locator.",
            )
        if len(current) > 1:
            return self._item(
                control,
                label,
                kind,
                ApplicationFieldCoverageStatus.AMBIGUOUS_BINDING,
                None,
                "Multiple approved bindings match this current required control.",
            )
        if not current:
            status = (
                ApplicationFieldCoverageStatus.STALE_BINDING
                if relevant
                else ApplicationFieldCoverageStatus.UNBOUND
            )
            reason = (
                "A prior binding exists, but it does not match the current portal page and control."
                if relevant
                else "No approved binding exists for this required control."
            )
            return self._item(control, label, kind, status, None, reason)

        binding = current[0]
        answer = self._answers.get_application_answer(binding.application_answer_id)
        if (
            answer is None
            or answer.application_id != binding.application_id
            or answer.revision != binding.answer_revision
        ):
            return self._item(
                control,
                label,
                kind,
                ApplicationFieldCoverageStatus.STALE_BINDING,
                binding.id,
                "The approved answer revision is missing or has changed since binding approval.",
            )
        if binding.automation_permission is not FieldAutomationPermission.AUTOFILL_ALLOWED:
            return self._item(
                control,
                label,
                kind,
                ApplicationFieldCoverageStatus.MANUAL_REQUIRED,
                binding.id,
                "The approved binding requires visible user handling.",
            )
        verified = any(
            execution.binding_id == binding.id
            and execution.answer_revision == binding.answer_revision
            and execution.page_fingerprint_before == run.page_fingerprint
            and execution.verified
            and not execution.error
            for execution in executions
        )
        status = (
            ApplicationFieldCoverageStatus.ALREADY_VERIFIED
            if verified
            else ApplicationFieldCoverageStatus.READY_TO_EXECUTE
        )
        reason = (
            "A verified execution exists for this binding, answer revision, and page."
            if verified
            else (
                "The current required control has one current binding eligible for "
                "individual execution review."
            )
        )
        return self._item(control, label, kind, status, binding.id, reason)

    @staticmethod
    def _item(
        control: BrowserObservedControl,
        label: str,
        kind: PortalFieldControlKind,
        status: ApplicationFieldCoverageStatus,
        binding_id: str | None,
        reason: str,
    ) -> ApplicationFieldCoverageItem:
        return ApplicationFieldCoverageItem(
            control_key=control.control_key,
            label=label,
            control_kind=kind,
            status=status,
            binding_id=binding_id,
            reason=reason,
        )
