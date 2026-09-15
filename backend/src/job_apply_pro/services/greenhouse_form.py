from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePath
from urllib.parse import urlsplit

from job_apply_pro.domain.browser import (
    BrowserActionKind,
    BrowserActionResult,
    BrowserControlKind,
    BrowserObservation,
    BrowserObservedControl,
    VerificationKind,
)
from job_apply_pro.domain.greenhouse_form import (
    GreenhouseControlContract,
    GreenhouseFormAction,
    GreenhouseFormContractAssessment,
    GreenhouseFormStage,
    GreenhousePostconditionEvidence,
    GreenhousePostconditionKind,
)


class GreenhouseFormContractError(ValueError):
    pass


GREENHOUSE_FORM_POLICY_VERSION = "greenhouse-form-execution-contract/1"

_STAGES = {
    "APPLICATION_FORM": GreenhouseFormStage.APPLICATION,
    "DOCUMENT_UPLOAD": GreenhouseFormStage.DOCUMENTS,
    "QUESTIONNAIRE": GreenhouseFormStage.QUESTIONNAIRE,
    "SUBMISSION_REVIEW": GreenhouseFormStage.REVIEW,
    "CONFIRMATION": GreenhouseFormStage.CONFIRMATION,
}
_STAGE_ORDER = {
    GreenhouseFormStage.APPLICATION: 1,
    GreenhouseFormStage.DOCUMENTS: 2,
    GreenhouseFormStage.QUESTIONNAIRE: 3,
    GreenhouseFormStage.REVIEW: 4,
    GreenhouseFormStage.CONFIRMATION: 5,
}
_FIELD_KINDS = {
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
_NAVIGATION_LABEL = re.compile(
    r"^(?:continue|next|review(?: application)?|save(?: and)? continue)$",
    re.IGNORECASE,
)
_SUBMIT_LABEL = re.compile(r"^(?:submit(?: application)?|apply now)$", re.IGNORECASE)
_DOCUMENT_SUFFIXES = {".doc", ".docx", ".pdf"}


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise GreenhouseFormContractError("Greenhouse form observations must use HTTPS")
    host = parsed.hostname.casefold()
    if host != "greenhouse.io" and not host.endswith(".greenhouse.io"):
        raise GreenhouseFormContractError("Observation is not on an allowed Greenhouse origin")
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://{host}{port}"


def _label(control: BrowserObservedControl) -> str:
    return next(
        (
            value.strip()
            for value in (
                control.label,
                control.group_label,
                control.text,
                control.field_name,
                control.kind.value,
            )
            if value.strip()
        ),
        control.kind.value,
    )[:300]


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _basename(value: str) -> str:
    return PurePath(value.replace("\\", "/")).name


class GreenhouseFormContractService:
    """Classify bounded Greenhouse observations without executing browser actions."""

    def assess(self, observation: BrowserObservation) -> GreenhouseFormContractAssessment:
        _origin(observation.url)
        stage = _STAGES.get(observation.page_type)
        if stage is None:
            raise GreenhouseFormContractError(
                f"Greenhouse form contract does not recognize {observation.page_type}"
            )

        controls = [
            contract
            for control in observation.controls
            if (contract := self._control_contract(control, observation)) is not None
        ]
        navigation = [
            control
            for control in observation.controls
            if control.visible
            and not control.disabled
            and not control.busy
            and control.kind in {BrowserControlKind.BUTTON, BrowserControlKind.LINK}
            and _NAVIGATION_LABEL.fullmatch(_label(control))
        ]
        submit = [
            control
            for control in observation.controls
            if control.visible
            and not control.disabled
            and control.kind is BrowserControlKind.BUTTON
            and _SUBMIT_LABEL.fullmatch(_label(control))
        ]

        if stage is GreenhouseFormStage.REVIEW:
            for control in submit:
                controls.append(
                    GreenhouseControlContract(
                        control_key=control.control_key,
                        label=_label(control),
                        control_kind=control.kind,
                        required=False,
                        blocking=True,
                        action=GreenhouseFormAction.FINAL_SUBMISSION_GATE,
                        postcondition=(GreenhousePostconditionKind.IDENTIFIER_BACKED_CONFIRMATION),
                        reason=(
                            "Final submission remains behind the separate default-off policy, "
                            "current-page review, and native confirmation gate."
                        ),
                    )
                )
        elif len(navigation) == 1:
            control = navigation[0]
            controls.append(
                GreenhouseControlContract(
                    control_key=control.control_key,
                    label=_label(control),
                    control_kind=control.kind,
                    required=False,
                    blocking=False,
                    action=GreenhouseFormAction.REVIEW_NAVIGATION,
                    postcondition=GreenhousePostconditionKind.NEXT_STAGE_OBSERVED,
                    reason=(
                        "Navigation requires a current assessment and a verified transition to "
                        "a recognized later Greenhouse stage."
                    ),
                )
            )

        required = [item for item in controls if item.required]
        satisfied = [item for item in required if item.action is GreenhouseFormAction.OBSERVE_ONLY]
        review_fields = [
            item for item in required if item.action is GreenhouseFormAction.REVIEW_FIELD
        ]
        uploads = [
            item for item in required if item.action is GreenhouseFormAction.REVIEW_DOCUMENT_UPLOAD
        ]
        manual = [
            item for item in required if item.action is GreenhouseFormAction.USER_INTERVENTION
        ]
        ready = (
            stage not in {GreenhouseFormStage.REVIEW, GreenhouseFormStage.CONFIRMATION}
            and len(navigation) == 1
            and len(satisfied) == len(required)
        )
        limitations = [
            "Replay and sanitized-fixture validation is not authorized live compatibility.",
            (
                "Observed upload filenames do not prove uploaded bytes; immutable document "
                "evidence remains separate."
            ),
            (
                "Custom widgets, legal attestations, signatures, and final submission remain "
                "manual or separately gated."
            ),
        ]
        payload: dict[str, object] = {
            "policy_version": GREENHOUSE_FORM_POLICY_VERSION,
            "page_fingerprint": observation.page_fingerprint,
            "page_type": observation.page_type,
            "stage": stage.value,
            "required": [
                {
                    "control_key": item.control_key,
                    "control_kind": item.control_kind.value,
                    "action": item.action.value,
                    "postcondition": item.postcondition.value,
                    "blocking": item.blocking,
                }
                for item in required
            ],
            "navigation_control_key": (navigation[0].control_key if len(navigation) == 1 else None),
            "ready_to_advance": ready,
            "validation_error_count": len(observation.validation_errors),
        }
        return GreenhouseFormContractAssessment(
            policy_version=GREENHOUSE_FORM_POLICY_VERSION,
            page_fingerprint=observation.page_fingerprint,
            page_type=observation.page_type,
            stage=stage,
            required_control_count=len(required),
            satisfied_required_count=len(satisfied),
            review_field_count=len(review_fields),
            upload_review_count=len(uploads),
            manual_intervention_count=len(manual),
            navigation_control_key=(navigation[0].control_key if len(navigation) == 1 else None),
            navigation_label=_label(navigation[0]) if len(navigation) == 1 else None,
            ready_to_advance=ready,
            controls=controls,
            limitations=limitations,
            review_fingerprint=_hash(payload),
        )

    def verify_navigation(
        self,
        before: BrowserObservation,
        result: BrowserActionResult,
        *,
        expected_review_fingerprint: str,
    ) -> GreenhousePostconditionEvidence:
        before_assessment = self.assess(before)
        control_key = before_assessment.navigation_control_key or "missing-navigation-control"
        reasons: list[str] = []
        try:
            after_assessment = self.assess(result.observation)
        except GreenhouseFormContractError:
            after_assessment = None
            reasons.append("The result is not a recognized Greenhouse form stage.")
        if before_assessment.review_fingerprint != expected_review_fingerprint:
            reasons.append("The reviewed Greenhouse form assessment changed before navigation.")
        if not before_assessment.ready_to_advance:
            reasons.append("Required controls are not all satisfied on the reviewed page.")
        if result.action.kind is not BrowserActionKind.CLICK:
            reasons.append("Greenhouse stage navigation requires one reviewed click action.")
        if not result.verified:
            reasons.append("The browser did not verify the reviewed navigation action.")
        try:
            same_origin = _origin(before.url) == _origin(result.observation.url)
        except GreenhouseFormContractError:
            same_origin = False
        if not same_origin:
            reasons.append("The navigation escaped the exact Greenhouse origin.")
        if result.observation.page_fingerprint == before.page_fingerprint:
            reasons.append("The page fingerprint did not change after navigation.")
        if after_assessment is not None and (
            _STAGE_ORDER[after_assessment.stage] <= _STAGE_ORDER[before_assessment.stage]
        ):
            reasons.append("The observed page is not a recognized later Greenhouse stage.")
        candidate = next(
            (
                control
                for control in before.controls
                if control.control_key == before_assessment.navigation_control_key
            ),
            None,
        )
        if candidate is None or candidate.locator != result.action.locator:
            reasons.append("The action did not target the uniquely reviewed navigation control.")
        return self._evidence(
            kind=GreenhousePostconditionKind.NEXT_STAGE_OBSERVED,
            before=before,
            after=result.observation,
            control_key=control_key,
            reasons=reasons,
        )

    def verify_upload(
        self,
        before: BrowserObservation,
        result: BrowserActionResult,
        *,
        control_key: str,
        expected_file_name: str,
    ) -> GreenhousePostconditionEvidence:
        before_assessment = self.assess(before)
        reasons: list[str] = []
        try:
            after_assessment = self.assess(result.observation)
        except GreenhouseFormContractError:
            after_assessment = None
            reasons.append("The upload result is not a recognized Greenhouse form stage.")
        file_name = _basename(expected_file_name)
        if (
            file_name != expected_file_name
            or PurePath(file_name).suffix.casefold() not in _DOCUMENT_SUFFIXES
        ):
            reasons.append("The expected upload name is not a bounded supported document filename.")
        if result.action.kind is not BrowserActionKind.UPLOAD:
            reasons.append("The browser result is not a document upload action.")
        if result.action.file_path is None or _basename(result.action.file_path) != file_name:
            reasons.append("The action did not use the exact reviewed staged document filename.")
        if result.action.verification.kind is not VerificationKind.NONE:
            reasons.append(
                "Upload proof must come from the post-action observation, not a value rule."
            )
        if not result.verified:
            reasons.append("The browser did not complete the reviewed upload action.")
        control = next((item for item in before.controls if item.control_key == control_key), None)
        if control is None or control.kind is not BrowserControlKind.FILE_UPLOAD:
            reasons.append("The reviewed Greenhouse upload control is missing or changed.")
        elif control.locator != result.action.locator:
            reasons.append("The action did not target the reviewed upload control.")
        try:
            same_origin = _origin(before.url) == _origin(result.observation.url)
        except GreenhouseFormContractError:
            same_origin = False
        if not same_origin:
            reasons.append("The upload escaped the exact Greenhouse origin.")
        if after_assessment is not None and after_assessment.stage is not before_assessment.stage:
            reasons.append("The upload result changed Greenhouse form stages unexpectedly.")
        prior_names = [_basename(value) for value in before.upload_status]
        if file_name in prior_names:
            reasons.append("The exact filename was already present before the reviewed upload.")
        observed_names = [_basename(value) for value in result.observation.upload_status]
        if observed_names.count(file_name) != 1:
            reasons.append("The exact staged document filename was not observed once after upload.")
        return self._evidence(
            kind=GreenhousePostconditionKind.UPLOAD_FILE_NAME_OBSERVED,
            before=before,
            after=result.observation,
            control_key=control_key,
            reasons=reasons,
        )

    @staticmethod
    def _control_contract(
        control: BrowserObservedControl, observation: BrowserObservation
    ) -> GreenhouseControlContract | None:
        if not control.visible or control.kind in {
            BrowserControlKind.BUTTON,
            BrowserControlKind.LINK,
        }:
            return None
        label = _label(control)
        required = control.required
        satisfied = (
            required
            and control.native_required
            and control.will_validate
            and control.constraint_satisfied
            and not control.accessible_invalid
            and not observation.validation_errors
        )
        if control.kind is BrowserControlKind.FILE_UPLOAD:
            if satisfied and bool(observation.upload_status):
                return GreenhouseControlContract(
                    control_key=control.control_key,
                    label=label,
                    control_kind=control.kind,
                    required=required,
                    blocking=False,
                    action=GreenhouseFormAction.OBSERVE_ONLY,
                    postcondition=GreenhousePostconditionKind.UPLOAD_FILE_NAME_OBSERVED,
                    reason=(
                        "The page reports a valid file control and an observed upload name; "
                        "exact document-byte retention remains separate."
                    ),
                )
            return GreenhouseControlContract(
                control_key=control.control_key,
                label=label,
                control_kind=control.kind,
                required=required,
                blocking=required,
                action=GreenhouseFormAction.REVIEW_DOCUMENT_UPLOAD,
                postcondition=GreenhousePostconditionKind.UPLOAD_FILE_NAME_OBSERVED,
                reason=(
                    "Document upload requires the immutable selected version, an exact control, "
                    "and post-action filename observation."
                ),
            )
        manual = (
            control.kind
            in {
                BrowserControlKind.CUSTOM,
                BrowserControlKind.SIGNATURE,
                BrowserControlKind.DISCLOSURE,
            }
            or control.legal_attestation
            or control.disabled
            or control.read_only
            or control.busy
            or control.inert
            or control.accessibility_hidden
            or control.repeat_count > 1
            or control.locator is None
        )
        if manual:
            return GreenhouseControlContract(
                control_key=control.control_key,
                label=label,
                control_kind=control.kind,
                required=required,
                blocking=required,
                action=GreenhouseFormAction.USER_INTERVENTION,
                postcondition=GreenhousePostconditionKind.USER_VERIFIED,
                reason=(
                    "This control requires visible user handling; custom widgets, legal controls, "
                    "ambiguous topology, and unsafe state never inherit generic execution "
                    "authority."
                ),
            )
        if satisfied:
            return GreenhouseControlContract(
                control_key=control.control_key,
                label=label,
                control_kind=control.kind,
                required=required,
                blocking=False,
                action=GreenhouseFormAction.OBSERVE_ONLY,
                postcondition=GreenhousePostconditionKind.REQUIRED_CONSTRAINT_VALID,
                reason=(
                    "The current native required control is constraint-valid; semantic review "
                    "and value privacy remain outside this metadata-only assessment."
                ),
            )
        if control.kind in _FIELD_KINDS:
            postcondition = {
                BrowserControlKind.SELECT: GreenhousePostconditionKind.SELECTED_LABEL_EQUALS,
                BrowserControlKind.RADIO_GROUP: GreenhousePostconditionKind.CHECKED_EQUALS,
                BrowserControlKind.CHECKBOX: GreenhousePostconditionKind.CHECKED_EQUALS,
            }.get(control.kind, GreenhousePostconditionKind.VALUE_EQUALS)
            return GreenhouseControlContract(
                control_key=control.control_key,
                label=label,
                control_kind=control.kind,
                required=required,
                blocking=required,
                action=GreenhouseFormAction.REVIEW_FIELD,
                postcondition=postcondition,
                reason=(
                    "The field may proceed only through the existing answer/binding/page review "
                    "and one-control verified execution gate."
                ),
            )
        return GreenhouseControlContract(
            control_key=control.control_key,
            label=label,
            control_kind=control.kind,
            required=required,
            blocking=required,
            action=GreenhouseFormAction.USER_INTERVENTION,
            postcondition=GreenhousePostconditionKind.USER_VERIFIED,
            reason="The observed control has no reviewed Greenhouse execution contract.",
        )

    @staticmethod
    def _evidence(
        *,
        kind: GreenhousePostconditionKind,
        before: BrowserObservation,
        after: BrowserObservation,
        control_key: str,
        reasons: list[str],
    ) -> GreenhousePostconditionEvidence:
        reason = (
            "The exact reviewed Greenhouse postcondition was observed."
            if not reasons
            else " ".join(reasons)
        )
        payload: dict[str, object] = {
            "policy_version": GREENHOUSE_FORM_POLICY_VERSION,
            "kind": kind.value,
            "before": before.page_fingerprint,
            "after": after.page_fingerprint,
            "control_key": control_key,
            "verified": not reasons,
            "reason": reason,
        }
        return GreenhousePostconditionEvidence(
            policy_version=GREENHOUSE_FORM_POLICY_VERSION,
            kind=kind,
            before_page_fingerprint=before.page_fingerprint,
            after_page_fingerprint=after.page_fingerprint,
            control_key=control_key,
            verified=not reasons,
            reason=reason,
            evidence_fingerprint=_hash(payload),
        )
