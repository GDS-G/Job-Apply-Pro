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
    BrowserPermission,
    BrowserSessionCreate,
    BrowserSessionSnapshot,
    ConfirmationState,
    LocatorStrategy,
    SemanticLocator,
)
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

    def resume(self, session_id: str) -> BrowserSessionSnapshot: ...

    def takeover(self, session_id: str) -> BrowserSessionSnapshot: ...

    def execute_action(self, session_id: str, action: BrowserAction) -> BrowserActionResult: ...

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

    def start(self, command: SupervisedPortalRunCreate) -> SupervisedPortalRunSnapshot:
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
            before=observation.page_fingerprint,
            after=observation.page_fingerprint,
            action_kind=None,
            verified=match is not None,
        )
        saved = self._repository.get(run.id)
        if saved is None:  # pragma: no cover - protected by repository transaction
            raise LookupError(f"Supervised portal run {run.id} was not found")
        return saved

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
        return self.get(run_id)

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
            action = self._submission_action(observation.controls)
            result = self._browser.execute_action(run.browser_session_id, action)
        except Exception:
            self._browser.takeover(run.browser_session_id)
            raise
        after = result.observation
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
        return run

    def list_runs(self) -> list[SupervisedPortalRunSnapshot]:
        return self._repository.list_runs()

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
                for value in (control.get("label"), control.get("text"))
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
    def _submission_action(controls: Iterable[dict[str, object]]) -> BrowserAction:
        candidates: list[str] = []
        for control in controls:
            tag = str(control.get("tag", "")).casefold()
            control_type = str(control.get("type", "")).casefold()
            if tag != "button" and control_type != "submit":
                continue
            label = next(
                (
                    str(control.get(key, "")).strip()
                    for key in ("label", "text", "name", "value")
                    if str(control.get(key, "")).strip()
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
