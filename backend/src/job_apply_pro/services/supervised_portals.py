from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionKind,
    BrowserActionResult,
    BrowserObservation,
    BrowserObservedControl,
    BrowserPermission,
    BrowserSessionCreate,
    BrowserSessionSnapshot,
    BrowserSessionState,
    BrowserVerification,
    ConfirmationState,
    LocatorStrategy,
    SemanticLocator,
    VerificationKind,
)
from job_apply_pro.domain.greenhouse_form import (
    GreenhouseFormAction,
    GreenhouseFormStage,
    GreenhousePostconditionEvidence,
)
from job_apply_pro.domain.knowledge import CandidateDocumentVersionRecord
from job_apply_pro.domain.portals import (
    PortalAdapterDefinition,
    PortalCapability,
    PortalInterventionReason,
    PortalKind,
    PortalPageMatch,
    SupervisedPortalCapture,
    SupervisedPortalDisposition,
    SupervisedPortalRunCreate,
    SupervisedPortalRunSnapshot,
    SupervisedPortalRunState,
    SupervisedPortalStepEvidence,
    SupervisedPortalSubmissionApproval,
)
from job_apply_pro.portals.catalog import PortalCatalog, PortalCatalogError
from job_apply_pro.services.greenhouse_form import (
    GreenhouseFormContractError,
    GreenhouseFormContractService,
)


class SupervisedPortalError(RuntimeError):
    pass


class SupervisedPortalPolicyError(SupervisedPortalError):
    pass


class SupervisedPortalStateError(SupervisedPortalError):
    pass


class SupervisedPortalRepositoryProtocol(Protocol):
    def save(self, run: SupervisedPortalRunSnapshot) -> SupervisedPortalRunSnapshot: ...

    def add_evidence(
        self, evidence: SupervisedPortalStepEvidence
    ) -> SupervisedPortalStepEvidence: ...

    def next_sequence(self, run_id: str) -> int: ...

    def get(self, run_id: str) -> SupervisedPortalRunSnapshot | None: ...

    def list_runs(self) -> list[SupervisedPortalRunSnapshot]: ...


class SupervisedBrowserProtocol(Protocol):
    def create_session(self, command: BrowserSessionCreate) -> BrowserSessionSnapshot: ...

    def get_session(self, session_id: str) -> BrowserSessionSnapshot: ...

    def resume(self, session_id: str) -> BrowserSessionSnapshot: ...

    def takeover(self, session_id: str) -> BrowserSessionSnapshot: ...

    def execute_action(self, session_id: str, action: BrowserAction) -> BrowserActionResult: ...

    def stage_encrypted_upload(
        self,
        session_id: str,
        *,
        version_id: str,
        encrypted_path: str,
        file_name: str,
        expected_sha256: str,
    ) -> str: ...

    def clear_staged_uploads(self, session_id: str) -> None: ...

    def stop(self, session_id: str) -> BrowserSessionSnapshot: ...


_INTERVENTION_CAPABILITIES = {
    PortalCapability.LOGIN: PortalInterventionReason.LOGIN,
    PortalCapability.MFA: PortalInterventionReason.MFA,
    PortalCapability.CAPTCHA: PortalInterventionReason.CAPTCHA,
    PortalCapability.ASSESSMENT: PortalInterventionReason.ASSESSMENT,
}
_SUBMIT_PATTERN = re.compile(r"\b(?:submit(?: application)?|send application|apply now)\b", re.I)
_CONFIRMATION_PATTERN = re.compile(
    r"\b(?:confirmation|application|reference)(?:\s+(?:number|id|code))?"
    r"\s*[:#-]?\s*((?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{3,})\b",
    re.I,
)


def parse_portal_allowlist(value: str) -> set[PortalKind]:
    allowed: set[PortalKind] = set()
    for item in value.split(","):
        normalized = item.strip().upper()
        if not normalized:
            continue
        try:
            portal = PortalKind(normalized)
        except ValueError as error:
            raise SupervisedPortalPolicyError(
                f"Unknown supervised portal allowlist entry: {normalized}"
            ) from error
        if portal is PortalKind.REFERENCE_ATS:
            raise SupervisedPortalPolicyError(
                "REFERENCE_ATS uses the dedicated deterministic adapter"
            )
        allowed.add(portal)
    return allowed


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SupervisedPortalPolicyError("Portal origins must use HTTP or HTTPS")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SupervisedPortalPolicyError("External supervised origins must use HTTPS")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname.casefold()}{port}"


def _portal_host_allowed(definition: PortalAdapterDefinition, url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold()
    if "*" in definition.domains:
        return bool(host)
    return any(host == value or host.endswith(f".{value}") for value in definition.domains)


class SupervisedPortalService:
    def __init__(
        self,
        repository: SupervisedPortalRepositoryProtocol,
        browser: SupervisedBrowserProtocol,
        catalog: PortalCatalog,
        *,
        enabled: bool,
        submission_enabled: bool,
        allowed_portals: set[PortalKind],
    ) -> None:
        self._repository = repository
        self._browser = browser
        self._catalog = catalog
        self._enabled = enabled
        self._submission_enabled = submission_enabled
        self._allowed_portals = allowed_portals
        self._greenhouse_forms = GreenhouseFormContractService()

    def start(self, command: SupervisedPortalRunCreate) -> SupervisedPortalRunSnapshot:
        if command.portal is PortalKind.GREENHOUSE:
            raise SupervisedPortalPolicyError(
                "Use the reviewed Greenhouse application launch route"
            )
        return self._start(command)

    def start_reviewed_greenhouse(
        self, command: SupervisedPortalRunCreate, review_fingerprint: str
    ) -> SupervisedPortalRunSnapshot:
        if command.portal is not PortalKind.GREENHOUSE:
            raise SupervisedPortalPolicyError("Reviewed Greenhouse launch accepts GREENHOUSE only")
        if not re.fullmatch(r"[a-f0-9]{64}", review_fingerprint):
            raise SupervisedPortalPolicyError("Reviewed Greenhouse launch fingerprint is invalid")
        return self._start(command, launch_review_fingerprint=review_fingerprint)

    def _start(
        self,
        command: SupervisedPortalRunCreate,
        *,
        launch_review_fingerprint: str | None = None,
    ) -> SupervisedPortalRunSnapshot:
        self._require_portal_policy(command.portal)
        definition = self._catalog.get(command.portal)
        start_url = str(command.start_url)
        if not _portal_host_allowed(definition, start_url):
            raise SupervisedPortalPolicyError(
                f"{definition.display_name} does not allow the requested start domain"
            )
        allowed_origins = sorted(
            {_origin(start_url), *(_origin(value) for value in command.allowed_origins)}
        )
        session = self._browser.create_session(
            BrowserSessionCreate(
                workflow_id=command.workflow_id,
                start_url=command.start_url,
                engine=command.engine,
                profile_name=command.profile_name,
                headless=False,
                allowed_origins=allowed_origins,
            )
        )
        observation = session.observation
        if observation is None:
            raise SupervisedPortalStateError("Browser session did not produce an observation")
        match, state, disposition, reasons = self._classify(command.portal, observation)
        takeover = self._browser.takeover(session.id)
        now = datetime.now(UTC)
        run = SupervisedPortalRunSnapshot(
            id=str(uuid4()),
            portal=command.portal,
            workflow_id=command.workflow_id,
            browser_session_id=session.id,
            state=state,
            current_url=observation.url,
            allowed_origins=takeover.allowed_origins,
            page_fingerprint=observation.page_fingerprint,
            current_match=match,
            disposition=disposition,
            intervention_reasons=reasons,
            evidence=[],
            created_at=now,
            updated_at=now,
        )
        self._repository.save(run)
        self._record_evidence(
            run,
            before=launch_review_fingerprint or observation.page_fingerprint,
            after=observation.page_fingerprint,
            action_kind=None,
            verified=match is not None,
        )
        saved = self._repository.get(run.id)
        if saved is None:  # pragma: no cover - protected by repository transaction
            raise LookupError(f"Supervised portal run {run.id} was not found")
        return self._with_runtime_observation(saved, observation)

    def capture(self, run_id: str, command: SupervisedPortalCapture) -> SupervisedPortalRunSnapshot:
        run = self._active(run_id)
        if command.prior_page_fingerprint != run.page_fingerprint:
            raise SupervisedPortalStateError(
                "Portal page fingerprint changed; refresh before capturing the next step"
            )
        session = self._browser.resume(run.browser_session_id)
        observation = session.observation
        if observation is None:
            self._browser.takeover(run.browser_session_id)
            raise SupervisedPortalStateError("Browser session did not produce an observation")
        try:
            self._require_allowed_observation(run.allowed_origins, observation.origin)
            match, state, disposition, reasons = self._classify(run.portal, observation)
        except Exception:
            self._browser.takeover(run.browser_session_id)
            raise
        trace_path = run.trace_path
        if state is SupervisedPortalRunState.SUBMISSION_CONFIRMED:
            stopped = self._browser.stop(run.browser_session_id)
            trace_path = stopped.trace_path
        else:
            self._browser.takeover(run.browser_session_id)
        updated = run.model_copy(
            update={
                "state": state,
                "current_url": observation.url,
                "page_fingerprint": observation.page_fingerprint,
                "current_match": match,
                "disposition": disposition,
                "intervention_reasons": reasons,
                "trace_path": trace_path,
                "updated_at": datetime.now(UTC),
            }
        )
        self._repository.save(updated)
        self._record_evidence(
            updated,
            before=run.page_fingerprint,
            after=observation.page_fingerprint,
            action_kind=None,
            verified=match is not None,
        )
        return self._with_runtime_observation(self.get(run_id), observation)

    def upload_reviewed_greenhouse_document(
        self,
        run_id: str,
        *,
        form_review_fingerprint: str,
        control_key: str,
        document: CandidateDocumentVersionRecord,
    ) -> SupervisedPortalRunSnapshot:
        run, before, control = self._review_greenhouse_control(
            run_id,
            form_review_fingerprint=form_review_fingerprint,
            control_key=control_key,
            expected_action=GreenhouseFormAction.REVIEW_DOCUMENT_UPLOAD,
        )
        try:
            staged_path = self._browser.stage_encrypted_upload(
                run.browser_session_id,
                version_id=document.id,
                encrypted_path=document.storage_path,
                file_name=document.file_name,
                expected_sha256=document.sha256,
            )
            action = BrowserAction(
                kind=BrowserActionKind.UPLOAD,
                locator=control.locator,
                file_path=staged_path,
                preconditions=[
                    BrowserVerification(
                        kind=VerificationKind.LOCATOR_VISIBLE,
                        locator=control.locator,
                    )
                ],
                intended_result="Upload the exact reviewed immutable application document",
                verification=BrowserVerification(kind=VerificationKind.NONE),
                permission=BrowserPermission.ELEVATED,
                confirmation=ConfirmationState.CONFIRMED,
                sensitive_value=True,
            )
            result = self._browser.execute_action(run.browser_session_id, action)
            postcondition = self._greenhouse_forms.verify_upload(
                before,
                result,
                control_key=control_key,
                expected_file_name=document.file_name,
            )
            return self._finish_greenhouse_action(run, result, postcondition)
        except Exception:
            self._takeover_if_active(run.browser_session_id)
            raise
        finally:
            self._browser.clear_staged_uploads(run.browser_session_id)

    def navigate_reviewed_greenhouse_form(
        self,
        run_id: str,
        *,
        form_review_fingerprint: str,
        control_key: str,
    ) -> SupervisedPortalRunSnapshot:
        run, before, control = self._review_greenhouse_control(
            run_id,
            form_review_fingerprint=form_review_fingerprint,
            control_key=control_key,
            expected_action=GreenhouseFormAction.REVIEW_NAVIGATION,
        )
        try:
            action = BrowserAction(
                kind=BrowserActionKind.CLICK,
                locator=control.locator,
                preconditions=[
                    BrowserVerification(
                        kind=VerificationKind.LOCATOR_VISIBLE,
                        locator=control.locator,
                    )
                ],
                intended_result="Advance the exact reviewed Greenhouse form by one control",
                verification=BrowserVerification(kind=VerificationKind.NONE),
                permission=BrowserPermission.ELEVATED,
                confirmation=ConfirmationState.CONFIRMED,
            )
            result = self._browser.execute_action(run.browser_session_id, action)
            postcondition = self._greenhouse_forms.verify_navigation(
                before,
                result,
                expected_review_fingerprint=form_review_fingerprint,
            )
            return self._finish_greenhouse_action(run, result, postcondition)
        except Exception:
            self._takeover_if_active(run.browser_session_id)
            raise

    def submit(
        self, run_id: str, approval: SupervisedPortalSubmissionApproval
    ) -> SupervisedPortalRunSnapshot:
        run = self._active(run_id)
        self._require_portal_policy(run.portal)
        if not self._submission_enabled:
            raise SupervisedPortalPolicyError(
                "Supervised final submission is disabled by local policy"
            )
        if run.state is not SupervisedPortalRunState.READY_TO_SUBMIT:
            raise SupervisedPortalStateError("Portal run is not ready for final submission")
        if approval.review_fingerprint != run.page_fingerprint:
            raise SupervisedPortalStateError(
                "Submission review fingerprint changed; capture and review again"
            )
        if approval.confirmation_phrase != "SUBMIT APPLICATION":
            raise SupervisedPortalPolicyError("Submission confirmation phrase is invalid")
        resumed = self._browser.resume(run.browser_session_id)
        observation = resumed.observation
        if observation is None:
            self._browser.takeover(run.browser_session_id)
            raise SupervisedPortalStateError("Browser session did not produce an observation")
        if observation.page_fingerprint != run.page_fingerprint:
            self._browser.takeover(run.browser_session_id)
            raise SupervisedPortalStateError(
                "Submission page changed after approval; capture and review again"
            )
        try:
            self._require_allowed_observation(run.allowed_origins, observation.origin)
            exact_greenhouse_control_key = None
            if run.portal is PortalKind.GREENHOUSE:
                if approval.greenhouse_form_review_fingerprint is None:
                    raise SupervisedPortalPolicyError(
                        "Greenhouse final submission requires the current form review"
                    )
                exact_greenhouse_control_key = self._greenhouse_submission_control(
                    observation,
                    approval.greenhouse_form_review_fingerprint,
                ).control_key
            elif approval.greenhouse_form_review_fingerprint is not None:
                raise SupervisedPortalPolicyError(
                    "Greenhouse form review is invalid for another portal"
                )
            action = self._submission_action(
                observation.controls,
                exact_control_key=exact_greenhouse_control_key,
            )
            result = self._browser.execute_action(run.browser_session_id, action)
        except Exception:
            self._browser.takeover(run.browser_session_id)
            raise
        after = result.observation
        try:
            self._require_allowed_observation(run.allowed_origins, after.origin)
        except SupervisedPortalPolicyError:
            match = None
            state = SupervisedPortalRunState.SUBMISSION_UNCERTAIN
            disposition = SupervisedPortalDisposition.CONFIRMATION_UNCERTAIN
            reasons = [PortalInterventionReason.USER_TAKEOVER]
        else:
            match, state, disposition, reasons = self._classify(run.portal, after)
        if not result.verified or state is not SupervisedPortalRunState.SUBMISSION_CONFIRMED:
            state = SupervisedPortalRunState.SUBMISSION_UNCERTAIN
            disposition = SupervisedPortalDisposition.CONFIRMATION_UNCERTAIN
            reasons = [PortalInterventionReason.USER_TAKEOVER]
            self._browser.takeover(run.browser_session_id)
            trace_path = run.trace_path
        else:
            stopped = self._browser.stop(run.browser_session_id)
            trace_path = stopped.trace_path
        updated = run.model_copy(
            update={
                "state": state,
                "current_url": after.url,
                "page_fingerprint": after.page_fingerprint,
                "current_match": match,
                "disposition": disposition,
                "intervention_reasons": reasons,
                "trace_path": trace_path,
                "updated_at": datetime.now(UTC),
            }
        )
        self._repository.save(updated)
        self._record_evidence(
            updated,
            before=run.page_fingerprint,
            after=after.page_fingerprint,
            action_kind=BrowserActionKind.CLICK,
            verified=result.verified and state is SupervisedPortalRunState.SUBMISSION_CONFIRMED,
        )
        return self.get(run_id)

    def _greenhouse_submission_control(
        self,
        observation: BrowserObservation,
        form_review_fingerprint: str,
    ) -> BrowserObservedControl:
        try:
            assessment = self._greenhouse_forms.assess(observation)
        except GreenhouseFormContractError as error:
            raise SupervisedPortalStateError(
                "Current page is not a recognized Greenhouse submission review"
            ) from error
        if assessment.review_fingerprint != form_review_fingerprint:
            raise SupervisedPortalStateError(
                "Greenhouse form review changed; capture and review again"
            )
        contracts = [
            item
            for item in assessment.controls
            if item.action is GreenhouseFormAction.FINAL_SUBMISSION_GATE
        ]
        if assessment.stage is not GreenhouseFormStage.REVIEW or len(contracts) != 1:
            raise SupervisedPortalPolicyError(
                "Greenhouse final submission requires exactly one reviewed submit control"
            )
        observed = [
            item
            for item in observation.controls
            if item.control_key == contracts[0].control_key and item.locator is not None
        ]
        if len(observed) != 1:
            raise SupervisedPortalPolicyError(
                "The reviewed Greenhouse submit control is missing, ambiguous, or unlocatable"
            )
        return observed[0]

    def stop(self, run_id: str) -> SupervisedPortalRunSnapshot:
        run = self._active(run_id)
        stopped = self._browser.stop(run.browser_session_id)
        updated = run.model_copy(
            update={
                "state": SupervisedPortalRunState.STOPPED,
                "disposition": SupervisedPortalDisposition.STOPPED,
                "intervention_reasons": [],
                "trace_path": stopped.trace_path,
                "updated_at": datetime.now(UTC),
            }
        )
        self._repository.save(updated)
        self._record_evidence(
            updated,
            before=run.page_fingerprint,
            after=run.page_fingerprint,
            action_kind=None,
            verified=True,
        )
        return self.get(run_id)

    def get(self, run_id: str) -> SupervisedPortalRunSnapshot:
        run = self._repository.get(run_id)
        if run is None:
            raise LookupError(f"Supervised portal run {run_id} was not found")
        session = self._browser.get_session(run.browser_session_id)
        observation = session.observation
        if observation is None or observation.page_fingerprint != run.page_fingerprint:
            return run.model_copy(update={"observed_controls": [], "greenhouse_form": None})
        return self._with_runtime_observation(run, observation)

    def _with_runtime_observation(
        self, run: SupervisedPortalRunSnapshot, observation: BrowserObservation
    ) -> SupervisedPortalRunSnapshot:
        greenhouse_form = None
        if run.portal is PortalKind.GREENHOUSE:
            try:
                greenhouse_form = self._greenhouse_forms.assess(observation)
            except GreenhouseFormContractError:
                greenhouse_form = None
        return run.model_copy(
            update={
                "observed_controls": observation.controls,
                "greenhouse_form": greenhouse_form,
            }
        )

    def _review_greenhouse_control(
        self,
        run_id: str,
        *,
        form_review_fingerprint: str,
        control_key: str,
        expected_action: GreenhouseFormAction,
    ) -> tuple[SupervisedPortalRunSnapshot, BrowserObservation, BrowserObservedControl]:
        run = self._active(run_id)
        self._require_portal_policy(run.portal)
        if run.portal is not PortalKind.GREENHOUSE:
            raise SupervisedPortalPolicyError("Reviewed Greenhouse actions accept GREENHOUSE only")
        try:
            resumed = self._browser.resume(run.browser_session_id)
            observation = resumed.observation
            if observation is None or observation.page_fingerprint != run.page_fingerprint:
                raise SupervisedPortalStateError(
                    "Greenhouse page changed after review; capture and review again"
                )
            self._require_allowed_observation(run.allowed_origins, observation.origin)
            assessment = self._greenhouse_forms.assess(observation)
            if assessment.review_fingerprint != form_review_fingerprint:
                raise SupervisedPortalStateError(
                    "Greenhouse form review changed; capture and review again"
                )
            contracts = [
                item
                for item in assessment.controls
                if item.control_key == control_key and item.action is expected_action
            ]
            observed = [item for item in observation.controls if item.control_key == control_key]
            if len(contracts) != 1 or len(observed) != 1 or observed[0].locator is None:
                raise SupervisedPortalPolicyError(
                    "The reviewed Greenhouse control is missing, ambiguous, or unlocatable"
                )
            if expected_action is GreenhouseFormAction.REVIEW_NAVIGATION and (
                not assessment.ready_to_advance or assessment.navigation_control_key != control_key
            ):
                raise SupervisedPortalStateError(
                    "Required Greenhouse controls are not ready for reviewed navigation"
                )
            return run, observation, observed[0]
        except Exception:
            self._takeover_if_active(run.browser_session_id)
            raise

    def _finish_greenhouse_action(
        self,
        run: SupervisedPortalRunSnapshot,
        result: BrowserActionResult,
        postcondition: GreenhousePostconditionEvidence,
    ) -> SupervisedPortalRunSnapshot:
        after = result.observation
        try:
            self._require_allowed_observation(run.allowed_origins, after.origin)
            allowed_origin = True
        except SupervisedPortalPolicyError:
            allowed_origin = False
        match, state, disposition, reasons = self._classify(run.portal, after)
        verified = result.verified and postcondition.verified and allowed_origin
        if not verified:
            state = SupervisedPortalRunState.INTERVENTION_REQUIRED
            disposition = SupervisedPortalDisposition.MANUAL_INTERVENTION_REQUIRED
            reasons = [PortalInterventionReason.SITE_CHANGED]
        updated = run.model_copy(
            update={
                "state": state,
                "current_url": after.url,
                "page_fingerprint": after.page_fingerprint,
                "current_match": match,
                "disposition": disposition,
                "intervention_reasons": reasons,
                "updated_at": datetime.now(UTC),
            }
        )
        self._repository.save(updated)
        self._record_evidence(
            updated,
            before=run.page_fingerprint,
            after=after.page_fingerprint,
            action_kind=result.action.kind,
            verified=verified,
            postcondition=postcondition,
        )
        self._takeover_if_active(run.browser_session_id)
        return self._with_runtime_observation(self.get(run.id), after)

    def _takeover_if_active(self, session_id: str) -> None:
        if self._browser.get_session(session_id).state is BrowserSessionState.ACTIVE:
            self._browser.takeover(session_id)

    def list_runs(self) -> list[SupervisedPortalRunSnapshot]:
        return [self.get(run.id) for run in self._repository.list_runs()]

    def _active(self, run_id: str) -> SupervisedPortalRunSnapshot:
        run = self.get(run_id)
        if run.state in {
            SupervisedPortalRunState.SUBMISSION_CONFIRMED,
            SupervisedPortalRunState.STOPPED,
        }:
            raise SupervisedPortalStateError(f"Supervised portal run is {run.state}")
        return run

    def _require_portal_policy(self, portal: PortalKind) -> None:
        if not self._enabled:
            raise SupervisedPortalPolicyError("Supervised portal execution is disabled")
        if portal is PortalKind.REFERENCE_ATS:
            raise SupervisedPortalPolicyError(
                "REFERENCE_ATS uses the dedicated deterministic adapter"
            )
        if portal not in self._allowed_portals:
            raise SupervisedPortalPolicyError(
                f"{portal.value} is not in the supervised portal allowlist"
            )

    def _classify(
        self, portal: PortalKind, observation: BrowserObservation
    ) -> tuple[
        PortalPageMatch | None,
        SupervisedPortalRunState,
        SupervisedPortalDisposition,
        list[PortalInterventionReason],
    ]:
        try:
            labels = [
                str(value)
                for control in observation.controls
                for value in (control.label, control.text)
                if value
            ]
            page_type = observation.page_type if observation.page_type != "UNKNOWN" else None
            try:
                match = self._catalog.identify(
                    url=observation.url,
                    page_type=page_type,
                    visible_text=observation.visible_text,
                    control_labels=labels,
                    page_fingerprint=observation.page_fingerprint,
                )
            except PortalCatalogError:
                if page_type is None:
                    raise
                match = self._catalog.identify(
                    url=observation.url,
                    page_type=None,
                    visible_text=observation.visible_text,
                    control_labels=labels,
                    page_fingerprint=observation.page_fingerprint,
                )
            if match.portal is not portal:
                raise PortalCatalogError("Observed portal does not match the supervised run")
        except PortalCatalogError:
            return (
                None,
                SupervisedPortalRunState.INTERVENTION_REQUIRED,
                SupervisedPortalDisposition.MANUAL_INTERVENTION_REQUIRED,
                [PortalInterventionReason.SITE_CHANGED],
            )
        intervention = _INTERVENTION_CAPABILITIES.get(match.capability)
        if intervention is not None:
            return (
                match,
                SupervisedPortalRunState.INTERVENTION_REQUIRED,
                SupervisedPortalDisposition.MANUAL_INTERVENTION_REQUIRED,
                [intervention],
            )
        if match.capability is PortalCapability.SUBMISSION:
            return (
                match,
                SupervisedPortalRunState.READY_TO_SUBMIT,
                SupervisedPortalDisposition.FINAL_CONFIRMATION_REQUIRED,
                [PortalInterventionReason.FINAL_SUBMISSION],
            )
        if match.capability is PortalCapability.CONFIRMATION:
            identifier = self._confirmation_identifier(observation.visible_text)
            verified = self._catalog.verify_confirmation(
                portal,
                page_type=match.page_type,
                visible_text=observation.visible_text,
                confirmation_identifier=identifier,
            )
            if verified:
                return (
                    match,
                    SupervisedPortalRunState.SUBMISSION_CONFIRMED,
                    SupervisedPortalDisposition.CONFIRMATION_VERIFIED,
                    [],
                )
            return (
                match,
                SupervisedPortalRunState.SUBMISSION_UNCERTAIN,
                SupervisedPortalDisposition.CONFIRMATION_UNCERTAIN,
                [PortalInterventionReason.USER_TAKEOVER],
            )
        return (
            match,
            SupervisedPortalRunState.AWAITING_USER,
            SupervisedPortalDisposition.USER_ACTION_REQUIRED,
            [PortalInterventionReason.USER_TAKEOVER],
        )

    @staticmethod
    def _confirmation_identifier(visible_text: str) -> str | None:
        match = _CONFIRMATION_PATTERN.search(visible_text)
        return match.group(1) if match else None

    @staticmethod
    def _submission_action(
        controls: Iterable[BrowserObservedControl],
        *,
        exact_control_key: str | None = None,
    ) -> BrowserAction:
        observed_controls = list(controls)
        if exact_control_key is not None:
            exact = [
                control
                for control in observed_controls
                if control.control_key == exact_control_key and control.locator is not None
            ]
            if len(exact) != 1:
                raise SupervisedPortalPolicyError(
                    "Final submission requires the exact reviewed submit control"
                )
            return BrowserAction(
                kind=BrowserActionKind.CLICK,
                locator=exact[0].locator,
                preconditions=[
                    BrowserVerification(
                        kind=VerificationKind.LOCATOR_VISIBLE,
                        locator=exact[0].locator,
                    )
                ],
                intended_result="Submit the exact reviewed application",
                permission=BrowserPermission.ELEVATED,
                confirmation=ConfirmationState.CONFIRMED,
            )
        candidates: list[str] = []
        for control in observed_controls:
            tag = control.tag.casefold()
            control_type = control.input_type.casefold()
            if tag != "button" and control_type != "submit":
                continue
            label = next(
                (
                    value.strip()
                    for value in (control.label, control.text, control.field_name)
                    if value.strip()
                ),
                "",
            )
            if label and _SUBMIT_PATTERN.search(label):
                candidates.append(label)
        unique = sorted(set(candidates))
        if len(unique) != 1:
            raise SupervisedPortalPolicyError(
                "Final submission requires exactly one unambiguous submit control"
            )
        return BrowserAction(
            kind=BrowserActionKind.CLICK,
            locator=SemanticLocator(
                strategy=LocatorStrategy.ROLE,
                value="button",
                name=unique[0],
                exact=True,
            ),
            intended_result="Submit the exact reviewed application",
            permission=BrowserPermission.ELEVATED,
            confirmation=ConfirmationState.CONFIRMED,
        )

    @staticmethod
    def _require_allowed_observation(allowed_origins: list[str], origin: str) -> None:
        if _origin(origin) not in allowed_origins:
            raise SupervisedPortalPolicyError(
                "Observed page escaped the supervised session origin allowlist"
            )

    def _record_evidence(
        self,
        run: SupervisedPortalRunSnapshot,
        *,
        before: str,
        after: str,
        action_kind: BrowserActionKind | None,
        verified: bool,
        postcondition: GreenhousePostconditionEvidence | None = None,
    ) -> None:
        sequence = self._repository.next_sequence(run.id)
        fingerprint_payload = {
            "run_id": run.id,
            "sequence": sequence,
            "disposition": run.disposition.value,
            "capability": (
                run.current_match.capability.value if run.current_match is not None else None
            ),
            "page_type": run.current_match.page_type if run.current_match else "UNKNOWN",
            "before": before,
            "after": after,
            "action_kind": action_kind.value if action_kind is not None else None,
            "verified": verified,
            "reasons": [value.value for value in run.intervention_reasons],
            "postcondition_kind": postcondition.kind.value if postcondition else None,
            "postcondition_evidence_fingerprint": (
                postcondition.evidence_fingerprint if postcondition else None
            ),
        }
        action_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self._repository.add_evidence(
            SupervisedPortalStepEvidence(
                id=str(uuid4()),
                run_id=run.id,
                sequence=sequence,
                disposition=run.disposition,
                capability=(
                    run.current_match.capability if run.current_match is not None else None
                ),
                page_type=run.current_match.page_type if run.current_match else "UNKNOWN",
                before_fingerprint=before,
                after_fingerprint=after,
                action_kind=action_kind,
                action_fingerprint=action_fingerprint,
                verified=verified,
                intervention_reasons=run.intervention_reasons,
                created_at=datetime.now(UTC),
            )
        )
