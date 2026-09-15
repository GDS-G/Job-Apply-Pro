from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from shutil import rmtree
from typing import Never, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionDisposition,
    BrowserActionKind,
    BrowserActionResult,
    BrowserFieldReconciliationApproval,
    BrowserFieldReconciliationPreview,
    BrowserFieldReconciliationResult,
    BrowserObservation,
    BrowserPermission,
    BrowserSessionCreate,
    BrowserSessionRecord,
    BrowserSessionSnapshot,
    BrowserSessionState,
    BrowserVerification,
    ConfirmationState,
    VerificationKind,
)
from job_apply_pro.domain.checkpoints import EncryptedCheckpointRecord
from job_apply_pro.domain.external_effects import (
    ExternalEffectKind,
    ExternalEffectReconciliationKind,
    ExternalEffectReconciliationStatus,
    ExternalEffectStatus,
)
from job_apply_pro.domain.workflow import utc_now
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.services.external_effects import (
    ExternalEffectConsumedError,
    ExternalEffectService,
)
from job_apply_pro.storage.external_effect_repository import ExternalEffectConflictError
from job_apply_pro.storage.repository_contracts import (
    BrowserRuntimeRepositoryProtocol,
    CheckpointRepositoryProtocol,
    WorkbenchRepositoryProtocol,
)


class BrowserRuntimeError(RuntimeError):
    pass


class BrowserPolicyError(BrowserRuntimeError):
    pass


class BrowserSessionStateError(BrowserRuntimeError):
    pass


class BrowserActionUncertainError(BrowserSessionStateError):
    pass


class BrowserReconciliationUnprovenError(BrowserSessionStateError):
    pass


_RECONCILABLE_FIELD_ACTIONS = {
    BrowserActionKind.FILL,
    BrowserActionKind.SELECT_LABEL,
    BrowserActionKind.CHOOSE_CONTROLLED_OPTION,
    BrowserActionKind.CHECK,
    BrowserActionKind.UNCHECK,
}
_RECONCILABLE_FIELD_VERIFICATIONS = {
    VerificationKind.VALUE_EQUALS,
    VerificationKind.SELECTED_LABEL_EQUALS,
    VerificationKind.CHECKED_EQUALS,
}
_FIELD_ACTION_INTENT = "Populate one explicitly approved application field"


class BrowserWorkerProtocol(Protocol):
    @property
    def running(self) -> bool: ...

    def call(
        self,
        method: str,
        params: dict[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]: ...


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BrowserPolicyError("Browser navigation requires an HTTP or HTTPS origin")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname.lower()}{port}"


def _is_loopback(origin: str) -> bool:
    hostname = urlsplit(origin).hostname
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _public_snapshot(record: BrowserSessionRecord) -> BrowserSessionSnapshot:
    return BrowserSessionSnapshot.model_validate(record.model_dump())


class BrowserRuntimeService:
    def __init__(
        self,
        repository: BrowserRuntimeRepositoryProtocol,
        workbench: WorkbenchRepositoryProtocol,
        checkpoints: CheckpointRepositoryProtocol,
        cipher: SensitiveDataCipher,
        worker: BrowserWorkerProtocol,
        external_effects: ExternalEffectService,
        *,
        browser_data_dir: Path,
        browser_artifact_dir: Path,
        default_headless: bool,
        automation_enabled: bool,
    ) -> None:
        self._repository = repository
        self._workbench = workbench
        self._checkpoints = checkpoints
        self._cipher = cipher
        self._worker = worker
        self._external_effects = external_effects
        self._browser_data_dir = browser_data_dir.resolve()
        self._browser_artifact_dir = browser_artifact_dir.resolve()
        self._default_headless = default_headless
        self._automation_enabled = automation_enabled

    def create_session(self, command: BrowserSessionCreate) -> BrowserSessionSnapshot:
        if self._workbench.get_snapshot(command.workflow_id) is None:
            raise LookupError(f"Workflow {command.workflow_id} was not found")
        start_url = str(command.start_url)
        start_origin = _origin(start_url)
        allowed_origins = {start_origin}
        allowed_origins.update(_origin(value) for value in command.allowed_origins)
        normalized_origins = sorted(allowed_origins)
        if not self._automation_enabled and not all(
            _is_loopback(origin) for origin in allowed_origins
        ):
            raise BrowserPolicyError(
                "External browser origins remain disabled; use a loopback fixture URL"
            )
        profile_history = [
            existing
            for existing in self._repository.list_snapshots()
            if existing.profile_name.casefold() == command.profile_name.casefold()
            and existing.engine is command.engine
        ]
        for existing in profile_history:
            if existing.state in {
                BrowserSessionState.STARTING,
                BrowserSessionState.ACTIVE,
                BrowserSessionState.USER_TAKEOVER,
            }:
                raise BrowserSessionStateError(
                    f"Browser profile {command.profile_name} is already in use"
                )
        if any(existing.profile_name != command.profile_name for existing in profile_history):
            raise BrowserPolicyError(
                "Browser profile names are case-insensitive; reuse the exact saved spelling"
            )
        historical_origin_sets = {
            tuple(sorted(existing.allowed_origins)) for existing in profile_history
        }
        if len(historical_origin_sets) > 1:
            raise BrowserPolicyError(
                "Browser profile has conflicting historical origin bindings; use a new profile name"
            )
        if historical_origin_sets and tuple(normalized_origins) not in historical_origin_sets:
            raise BrowserPolicyError(
                "Browser profile is already bound to another exact origin set; "
                "use a new profile name"
            )
        session_id = str(uuid4())
        now = utc_now()
        profile_dir = (
            self._browser_data_dir / command.engine.value / command.profile_name
        ).resolve()
        artifact_dir = (self._browser_artifact_dir / session_id).resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        record = BrowserSessionRecord(
            id=session_id,
            workflow_id=command.workflow_id,
            engine=command.engine,
            profile_name=command.profile_name,
            state=BrowserSessionState.STARTING,
            current_url=start_url,
            allowed_origins=normalized_origins,
            observation=None,
            action_count=0,
            trace_path=None,
            created_at=now,
            updated_at=now,
            user_data_dir=str(profile_dir),
            artifact_dir=str(artifact_dir),
            headless=self._default_headless if command.headless is None else command.headless,
        )
        self._repository.add(record)
        try:
            result = self._worker.call(
                "start_session",
                {
                    "session_id": session_id,
                    "workflow_id": command.workflow_id,
                    "engine": command.engine.value,
                    "profile_dir": str(profile_dir),
                    "artifact_dir": str(artifact_dir),
                    "start_url": start_url,
                    "current_url": start_url,
                    "allowed_origins": normalized_origins,
                    "headless": record.headless,
                },
            )
            observation = BrowserObservation.model_validate(result)
            self._validate_observation(record, observation)
            saved = self._repository.save_observation(
                session_id, BrowserSessionState.ACTIVE, observation
            )
            self._save_checkpoint(saved, observation, pending_action=None)
            return _public_snapshot(saved)
        except Exception:
            self._repository.set_state(session_id, BrowserSessionState.FAILED)
            raise

    def get_session(self, session_id: str) -> BrowserSessionSnapshot:
        return _public_snapshot(self._record(session_id))

    def list_sessions(self, workflow_id: str | None = None) -> list[BrowserSessionSnapshot]:
        return self._repository.list_snapshots(workflow_id)

    def observe(self, session_id: str) -> BrowserSessionSnapshot:
        record = self._active_record(session_id, allow_takeover=True)
        result = self._worker.call("observe", {"session_id": session_id})
        observation = BrowserObservation.model_validate(result)
        self._validate_live_observation(record, observation)
        saved = self._repository.save_observation(session_id, record.state, observation)
        return _public_snapshot(saved)

    def execute_action(self, session_id: str, action: BrowserAction) -> BrowserActionResult:
        record = self._active_record(session_id)
        self._ensure_no_unresolved_effect(session_id)
        self._validate_action(record, action)
        source_observation = record.observation
        reconcilable_field_action = self._is_reconcilable_field_action(action)
        if reconcilable_field_action and source_observation is None:
            raise BrowserPolicyError(
                "Reviewed field execution requires a current browser observation"
            )
        sequence = self._repository.next_action_sequence(session_id)
        action_request = action.model_dump(mode="json")
        effect_key = f"browser:{session_id}:{sequence}"
        # The ledger owns an independent transaction. End the repository's read
        # transaction so SQLite can durably commit admission before worker I/O.
        self._repository.release_transaction()
        try:
            admission = self._external_effects.admit(
                effect_key=effect_key,
                kind=ExternalEffectKind.BROWSER_ACTION,
                subject_type="browser_session",
                subject_id=session_id,
                actor="browser-runtime",
                request=action_request,
            )
            operation = self._external_effects.require_fresh(admission).operation
            attempt = self._external_effects.prepare_attempt(
                operation.id,
                provider="playwright",
                target_code=action.kind.value,
                request=action_request,
                native_key=effect_key,
            )
            if reconcilable_field_action:
                assert source_observation is not None  # validated before durable admission
                self._external_effects.prepare_browser_field_reconciliation(
                    operation.id,
                    attempt.id,
                    payload={
                        "action_kind": action.kind.value,
                        "verification": action.verification.model_dump(mode="json"),
                        "request_fingerprint": operation.request_fingerprint,
                    },
                    source_page_fingerprint=source_observation.page_fingerprint,
                    actor="browser-runtime",
                )
            self._external_effects.begin_dispatch(operation.id, attempt.id)
        except (ExternalEffectConflictError, ExternalEffectConsumedError) as error:
            if self._external_effects.has_unresolved_subject("browser_session", session_id):
                self._repository.set_state(session_id, BrowserSessionState.USER_TAKEOVER)
            raise BrowserSessionStateError(
                "Browser action admission is already consumed or requires reconciliation"
            ) from error

        try:
            result = self._worker.call(
                "execute",
                {"session_id": session_id, "action": action_request},
                timeout_seconds=max(75, action.timeout_ms / 1_000 + 10),
            )
        except Exception as error:
            self._raise_uncertain_action(
                record,
                action,
                sequence=sequence,
                operation_id=operation.id,
                attempt_id=attempt.id,
                observation=record.observation,
                error_code="WORKER_RESPONSE_UNAVAILABLE",
                cause=error,
            )

        try:
            disposition = BrowserActionDisposition(str(result.get("disposition")))
            observation = BrowserObservation.model_validate(result.get("observation"))
            self._validate_live_observation(record, observation)
        except BrowserPolicyError as error:
            self._raise_uncertain_action(
                record,
                action,
                sequence=sequence,
                operation_id=operation.id,
                attempt_id=attempt.id,
                observation=record.observation,
                error_code="ORIGIN_POLICY_VIOLATION",
                cause=error,
            )
        except Exception as error:
            self._raise_uncertain_action(
                record,
                action,
                sequence=sequence,
                operation_id=operation.id,
                attempt_id=attempt.id,
                observation=record.observation,
                error_code="WORKER_PROTOCOL_INVALID",
                cause=error,
            )

        worker_error = result.get("error_code")
        error_code = worker_error if isinstance(worker_error, str) else None
        valid = result.get("attempts") == 1 and (
            (
                disposition is BrowserActionDisposition.CONFIRMED
                and result.get("verified") is True
                and error_code is None
            )
            or (
                disposition is BrowserActionDisposition.NOT_APPLIED
                and result.get("verified") is False
                and error_code == "PRECONDITION_FAILED"
            )
            or (
                disposition is BrowserActionDisposition.UNCERTAIN
                and result.get("verified") is False
                and error_code
                in {
                    "ACTION_EXECUTION_UNCERTAIN",
                    "POSTCONDITION_UNVERIFIED",
                    "PRECONDITION_PROOF_UNAVAILABLE",
                }
            )
        )
        if not valid:
            self._raise_uncertain_action(
                record,
                action,
                sequence=sequence,
                operation_id=operation.id,
                attempt_id=attempt.id,
                observation=observation,
                error_code="WORKER_PROTOCOL_INVALID",
            )
        if disposition is BrowserActionDisposition.UNCERTAIN:
            self._raise_uncertain_action(
                record,
                action,
                sequence=sequence,
                operation_id=operation.id,
                attempt_id=attempt.id,
                observation=observation,
                error_code=error_code or "ACTION_EXECUTION_UNCERTAIN",
            )

        action_result = BrowserActionResult(
            id=attempt.id,
            session_id=session_id,
            sequence=sequence,
            action=action,
            verified=disposition is BrowserActionDisposition.CONFIRMED,
            attempts=1,
            observation=observation,
            error=error_code,
            created_at=datetime.now(UTC),
        )
        try:
            self._repository.add_action(action_result)
        except Exception as error:
            self._raise_uncertain_action(
                record,
                action,
                sequence=sequence,
                operation_id=operation.id,
                attempt_id=attempt.id,
                observation=observation,
                error_code="LOCAL_EVIDENCE_PERSIST_FAILED",
                cause=error,
                persist_action=False,
            )
        updated = self._record(session_id)
        try:
            self._save_checkpoint(updated, observation, pending_action=None)
        except Exception:
            # The durable action row is authoritative, but pause subsequent
            # automation when the secondary recovery checkpoint could not advance.
            self._repository.set_state(session_id, BrowserSessionState.USER_TAKEOVER)
        if disposition is BrowserActionDisposition.CONFIRMED:
            self._external_effects.finish(
                operation.id,
                attempt.id,
                status=ExternalEffectStatus.CONFIRMED,
                result_reference=f"browser-action:{attempt.id}",
                result={
                    "verified": True,
                    "page_fingerprint": observation.page_fingerprint,
                },
            )
        else:
            self._external_effects.finish(
                operation.id,
                attempt.id,
                status=ExternalEffectStatus.FAILED,
                error_code="PRECONDITION_FAILED",
            )
        return action_result

    def takeover(self, session_id: str) -> BrowserSessionSnapshot:
        self._active_record(session_id)
        return _public_snapshot(
            self._repository.set_state(session_id, BrowserSessionState.USER_TAKEOVER)
        )

    def resume(self, session_id: str) -> BrowserSessionSnapshot:
        record = self._record(session_id)
        if record.state is not BrowserSessionState.USER_TAKEOVER:
            raise BrowserSessionStateError("Browser session is not in user takeover")
        self._ensure_no_unresolved_effect(session_id)
        result = self._worker.call("observe", {"session_id": session_id})
        observation = BrowserObservation.model_validate(result)
        self._validate_live_observation(record, observation)
        saved = self._repository.save_observation(
            session_id, BrowserSessionState.ACTIVE, observation
        )
        self._save_checkpoint(saved, observation, pending_action=None)
        return _public_snapshot(saved)

    def restart(self, session_id: str) -> BrowserSessionSnapshot:
        self._active_record(session_id, allow_takeover=True)
        self._ensure_no_unresolved_effect(session_id)
        result = self._worker.call("restart_session", {"session_id": session_id})
        observation = BrowserObservation.model_validate(result)
        self._validate_live_observation(self._record(session_id), observation)
        saved = self._repository.save_observation(
            session_id, BrowserSessionState.ACTIVE, observation
        )
        self._save_checkpoint(saved, observation, pending_action=None)
        return _public_snapshot(saved)

    def stop(self, session_id: str) -> BrowserSessionSnapshot:
        record = self._active_record(session_id, allow_takeover=True)
        try:
            result = self._worker.call("stop_session", {"session_id": session_id})
            trace_path = str(result["trace_path"]) if result.get("trace_path") else None
            stopped = self._repository.set_state(
                session_id, BrowserSessionState.STOPPED, trace_path=trace_path
            )
            if record.observation is not None:
                self._save_checkpoint(stopped, record.observation, pending_action=None)
            return _public_snapshot(stopped)
        finally:
            rmtree(Path(record.artifact_dir) / "staged-uploads", ignore_errors=True)

    def list_actions(self, session_id: str) -> list[BrowserActionResult]:
        self._record(session_id)
        return self._repository.list_actions(session_id)

    def preview_field_reconciliation(
        self, session_id: str, operation_id: str
    ) -> BrowserFieldReconciliationPreview:
        preview, _observation, _evidence = self._prove_field_reconciliation(
            session_id, operation_id
        )
        return preview

    def approve_field_reconciliation(
        self,
        session_id: str,
        approval: BrowserFieldReconciliationApproval,
    ) -> BrowserFieldReconciliationResult:
        preview, observation, evidence = self._prove_field_reconciliation(
            session_id, approval.operation_id
        )
        if preview.review_fingerprint != approval.expected_review_fingerprint:
            raise BrowserReconciliationUnprovenError(
                "Browser field reconciliation changed after review"
            )
        saved = self._repository.save_observation(
            session_id, BrowserSessionState.USER_TAKEOVER, observation
        )
        self._save_checkpoint(saved, observation, pending_action=None)
        try:
            effect = self._external_effects.reconcile_browser_field(
                preview.operation_id,
                preview.attempt_id,
                evidence_reference=f"browser-action:{preview.attempt_id}",
                evidence=evidence,
                page_fingerprint=observation.page_fingerprint,
            )
        except (ExternalEffectConflictError, ValueError) as error:
            raise BrowserReconciliationUnprovenError(
                "Browser field reconciliation ownership changed"
            ) from error
        reconciliation = effect.reconciliation
        if (
            reconciliation is None
            or reconciliation.status is not ExternalEffectReconciliationStatus.CONFIRMED_APPLIED
            or reconciliation.reconciled_at is None
        ):  # pragma: no cover - repository contract
            raise RuntimeError("Browser field reconciliation did not become durable")
        return BrowserFieldReconciliationResult(
            operation_id=preview.operation_id,
            attempt_id=preview.attempt_id,
            session_id=session_id,
            action_kind=preview.action_kind,
            page_fingerprint=observation.page_fingerprint,
            reconciliation_kind=ExternalEffectReconciliationKind.BROWSER_FIELD_VALUE_CONFIRMED.value,
            reconciled_at=reconciliation.reconciled_at,
            notice=(
                "The exact reviewed field postcondition was observed and recorded. "
                "The original uncertain attempt remains immutable and was not retried."
            ),
        )

    def stage_encrypted_upload(
        self,
        session_id: str,
        *,
        version_id: str,
        encrypted_path: str,
        file_name: str,
        expected_sha256: str,
    ) -> str:
        record = self._active_record(session_id)
        source = Path(encrypted_path).resolve()
        safe_name = Path(file_name).name
        if not source.is_file() or not source.is_relative_to(self._browser_data_dir.parent):
            raise BrowserPolicyError("Encrypted document is outside the approved runtime directory")
        if not safe_name or safe_name != file_name:
            raise BrowserPolicyError("Upload filename must not contain a path")
        upload_dir = (Path(record.artifact_dir) / "staged-uploads").resolve()
        if not upload_dir.is_relative_to(Path(record.artifact_dir).resolve()):
            raise BrowserPolicyError("Upload staging directory escaped the browser session")
        destination = upload_dir / safe_name
        plaintext = self._cipher.decrypt_bytes(
            source.read_text(encoding="ascii"),
            context=f"document:{version_id}:file",
        )
        if (
            len(expected_sha256) != 64
            or any(value not in "0123456789abcdef" for value in expected_sha256)
            or hashlib.sha256(plaintext).hexdigest() != expected_sha256
        ):
            raise BrowserPolicyError("Immutable upload bytes do not match the reviewed document")
        upload_dir.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(plaintext)
        return str(destination)

    def clear_staged_uploads(self, session_id: str) -> None:
        record = self._record(session_id)
        rmtree(Path(record.artifact_dir) / "staged-uploads", ignore_errors=True)

    def _record(self, session_id: str) -> BrowserSessionRecord:
        record = self._repository.get_record(session_id)
        if record is None:
            raise LookupError(f"Browser session {session_id} was not found")
        return record

    def _prove_field_reconciliation(
        self, session_id: str, operation_id: str
    ) -> tuple[
        BrowserFieldReconciliationPreview,
        BrowserObservation,
        dict[str, object],
    ]:
        session = self._record(session_id)
        if session.state is not BrowserSessionState.USER_TAKEOVER:
            raise BrowserSessionStateError("Browser field reconciliation requires user takeover")
        effect = self._external_effects.get(operation_id)
        if (
            effect is None
            or effect.operation.kind is not ExternalEffectKind.BROWSER_ACTION
            or effect.operation.subject_type != "browser_session"
            or effect.operation.subject_id != session_id
            or effect.operation.status is not ExternalEffectStatus.UNCERTAIN
            or effect.reconciliation is None
            or effect.reconciliation.status is not ExternalEffectReconciliationStatus.AVAILABLE
            or len(effect.attempts) != 1
        ):
            raise BrowserReconciliationUnprovenError(
                "External effect is not an available uncertain browser field"
            )
        attempt = effect.attempts[0]
        intent = effect.reconciliation
        if (
            attempt.id != intent.attempt_id
            or attempt.status is not ExternalEffectStatus.UNCERTAIN
            or attempt.provider != "playwright"
        ):
            raise BrowserReconciliationUnprovenError(
                "Uncertain browser field attempt does not match its durable intent"
            )
        actions = [
            item for item in self._repository.list_actions(session_id) if item.id == attempt.id
        ]
        if len(actions) != 1:
            raise BrowserReconciliationUnprovenError(
                "Uncertain browser field has no unique local action evidence"
            )
        action_result = actions[0]
        action = action_result.action
        try:
            payload = self._external_effects.browser_field_reconciliation_payload(intent)
        except ValueError:
            raise BrowserReconciliationUnprovenError(
                "Encrypted browser reconciliation intent is invalid"
            ) from None
        if set(payload) != {"action_kind", "verification", "request_fingerprint"}:
            raise BrowserReconciliationUnprovenError(
                "Encrypted browser reconciliation intent is invalid"
            )
        try:
            action_kind = BrowserActionKind(str(payload["action_kind"]))
            verification_value = payload["verification"]
            if not isinstance(verification_value, dict):
                raise ValueError
            verification = BrowserVerification.model_validate(verification_value)
        except (TypeError, ValueError):
            raise BrowserReconciliationUnprovenError(
                "Encrypted browser reconciliation intent is invalid"
            ) from None
        if (
            action_kind not in _RECONCILABLE_FIELD_ACTIONS
            or verification.kind not in _RECONCILABLE_FIELD_VERIFICATIONS
            or verification.locator is None
            or action.kind is not action_kind
            or action.locator != verification.locator
            or action.intended_result != _FIELD_ACTION_INTENT
            or action.permission is not BrowserPermission.ELEVATED
            or action.confirmation is not ConfirmationState.CONFIRMED
            or not action.sensitive_value
            or action_result.verified
            or action_result.error is None
            or attempt.target_code != action_kind.value
            or payload["request_fingerprint"] != effect.operation.request_fingerprint
            or intent.source_page_fingerprint != action_result.observation.page_fingerprint
        ):
            raise BrowserReconciliationUnprovenError(
                "Uncertain browser action is outside the reviewed field contract"
            )
        result = self._worker.call(
            "verify_postcondition",
            {
                "session_id": session_id,
                "verification": verification.model_dump(mode="json"),
            },
            timeout_seconds=75,
        )
        if set(result) != {"verified", "observation", "error_code"}:
            raise BrowserReconciliationUnprovenError(
                "Browser reconciliation worker response is invalid"
            )
        try:
            observation = BrowserObservation.model_validate(result["observation"])
            self._validate_live_observation(session, observation)
        except (TypeError, ValueError, BrowserPolicyError):
            raise BrowserReconciliationUnprovenError(
                "Browser reconciliation observation is invalid"
            ) from None
        if (
            result["verified"] is not True
            or result["error_code"] is not None
            or observation.page_fingerprint != intent.source_page_fingerprint
            or observation.origin != action_result.observation.origin
            or observation.page_type != action_result.observation.page_type
        ):
            raise BrowserReconciliationUnprovenError(
                "Current page does not prove the exact reviewed field postcondition"
            )
        evidence: dict[str, object] = {
            "policy_version": ExternalEffectService.RECONCILIATION_POLICY_VERSION,
            "operation_id": effect.operation.id,
            "attempt_id": attempt.id,
            "session_id": session_id,
            "action_kind": action_kind.value,
            "verification_kind": verification.kind.value,
            "request_fingerprint": effect.operation.request_fingerprint,
            "source_page_fingerprint": intent.source_page_fingerprint,
            "result_page_fingerprint": observation.page_fingerprint,
            "origin": observation.origin,
            "page_type": observation.page_type,
        }
        review_fingerprint = self._external_effects.request_fingerprint(evidence)
        return (
            BrowserFieldReconciliationPreview(
                operation_id=effect.operation.id,
                attempt_id=attempt.id,
                session_id=session_id,
                action_kind=action_kind,
                verification_kind=verification.kind,
                page_fingerprint=observation.page_fingerprint,
                review_fingerprint=review_fingerprint,
                notice=(
                    "The exact encrypted field postcondition is currently observed. "
                    "Approval records reconciliation without repeating the browser action."
                ),
            ),
            observation,
            evidence,
        )

    @staticmethod
    def _is_reconcilable_field_action(action: BrowserAction) -> bool:
        return (
            action.kind in _RECONCILABLE_FIELD_ACTIONS
            and action.verification.kind in _RECONCILABLE_FIELD_VERIFICATIONS
            and action.locator is not None
            and action.verification.locator == action.locator
            and action.intended_result == _FIELD_ACTION_INTENT
            and action.permission is BrowserPermission.ELEVATED
            and action.confirmation is ConfirmationState.CONFIRMED
            and action.sensitive_value
        )

    def _active_record(
        self, session_id: str, *, allow_takeover: bool = False
    ) -> BrowserSessionRecord:
        record = self._record(session_id)
        valid_states = {BrowserSessionState.ACTIVE}
        if allow_takeover:
            valid_states.add(BrowserSessionState.USER_TAKEOVER)
        if record.state not in valid_states:
            raise BrowserSessionStateError(
                f"Browser session {session_id} is {record.state}, not active"
            )
        return record

    def _ensure_no_unresolved_effect(self, session_id: str) -> None:
        if self._external_effects.has_unresolved_subject("browser_session", session_id):
            self._repository.set_state(session_id, BrowserSessionState.USER_TAKEOVER)
            raise BrowserSessionStateError(
                "Browser session has an unresolved external action; reconcile it before resuming"
            )

    def _raise_uncertain_action(
        self,
        record: BrowserSessionRecord,
        action: BrowserAction,
        *,
        sequence: int,
        operation_id: str,
        attempt_id: str,
        observation: BrowserObservation | None,
        error_code: str,
        cause: Exception | None = None,
        persist_action: bool = True,
    ) -> Never:
        trusted_observation = observation or record.observation
        if trusted_observation is None:
            error_code = "LOCAL_EVIDENCE_UNAVAILABLE"
        elif persist_action:
            uncertain_result = BrowserActionResult(
                id=attempt_id,
                session_id=record.id,
                sequence=sequence,
                action=action,
                verified=False,
                attempts=1,
                observation=trusted_observation,
                error=error_code,
                created_at=datetime.now(UTC),
            )
            try:
                self._repository.add_action(uncertain_result)
                updated = self._record(record.id)
                self._save_checkpoint(updated, trusted_observation, pending_action=action)
            except Exception:
                error_code = "LOCAL_EVIDENCE_PERSIST_FAILED"
        try:
            self._repository.set_state(record.id, BrowserSessionState.USER_TAKEOVER)
        finally:
            self._external_effects.finish(
                operation_id,
                attempt_id,
                status=ExternalEffectStatus.UNCERTAIN,
                error_code=error_code,
            )
        raise BrowserActionUncertainError(
            "Browser action outcome is uncertain; automatic retry is blocked pending reconciliation"
        ) from cause

    def _validate_action(self, record: BrowserSessionRecord, action: BrowserAction) -> None:
        if action.confirmation is ConfirmationState.REQUIRED:
            raise BrowserPolicyError("Browser action still requires user confirmation")
        if (
            action.permission is BrowserPermission.ELEVATED
            and action.confirmation is not ConfirmationState.CONFIRMED
        ):
            raise BrowserPolicyError("Elevated browser actions require confirmed user approval")
        if action.kind is BrowserActionKind.NAVIGATE and (
            action.url is None or _origin(str(action.url)) not in record.allowed_origins
        ):
            raise BrowserPolicyError("Navigation target is outside the session allowlist")
        if action.kind is BrowserActionKind.UPLOAD:
            if action.file_path is None:
                raise BrowserPolicyError("Upload action requires an approved file path")
            upload_path = Path(action.file_path).resolve()
            approved_root = self._browser_data_dir.parent
            if not upload_path.is_file() or not upload_path.is_relative_to(approved_root):
                raise BrowserPolicyError("Upload path is outside the approved runtime directory")

    @staticmethod
    def _validate_observation(
        record: BrowserSessionRecord, observation: BrowserObservation
    ) -> None:
        if observation.origin not in record.allowed_origins:
            raise BrowserPolicyError("Browser observation escaped the session origin allowlist")

    def _validate_live_observation(
        self, record: BrowserSessionRecord, observation: BrowserObservation
    ) -> None:
        try:
            self._validate_observation(record, observation)
        except BrowserPolicyError:
            self._repository.set_state(record.id, BrowserSessionState.USER_TAKEOVER)
            raise

    def _save_checkpoint(
        self,
        record: BrowserSessionRecord,
        observation: BrowserObservation,
        *,
        pending_action: BrowserAction | None,
    ) -> None:
        workflow = self._workbench.get_snapshot(record.workflow_id)
        if workflow is None:
            raise LookupError(f"Workflow {record.workflow_id} was not found")
        sequence = self._checkpoints.next_sequence(record.workflow_id)
        payload: dict[str, object] = {
            "browser_session_id": record.id,
            "portal_origin": observation.origin,
            "page_type": observation.page_type,
            "url": observation.url,
            "browser_storage_reference": record.user_data_dir,
            "screenshot_path": observation.screenshot_path,
            "trace_path": record.trace_path,
            "pending_action": (
                pending_action.model_dump(mode="json") if pending_action is not None else None
            ),
            "retry_count": 0,
        }
        checkpoint = EncryptedCheckpointRecord(
            id=str(uuid4()),
            workflow_id=record.workflow_id,
            sequence=sequence,
            state=workflow.state,
            page_fingerprint=observation.page_fingerprint,
            encrypted_payload=self._cipher.encrypt_json(
                payload, context=f"checkpoint:{record.workflow_id}:{sequence}"
            ),
            created_at=utc_now(),
        )
        self._checkpoints.add_encrypted(checkpoint)
