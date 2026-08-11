from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from shutil import rmtree
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
    BrowserSessionRecord,
    BrowserSessionSnapshot,
    BrowserSessionState,
    ConfirmationState,
)
from job_apply_pro.domain.checkpoints import EncryptedCheckpointRecord
from job_apply_pro.domain.workflow import utc_now
from job_apply_pro.security.encryption import SensitiveDataCipher
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
        if not self._automation_enabled and not all(
            _is_loopback(origin) for origin in allowed_origins
        ):
            raise BrowserPolicyError(
                "External browser origins remain disabled; use a loopback fixture URL"
            )
        for existing in self._repository.list_snapshots():
            if (
                existing.profile_name == command.profile_name
                and existing.engine is command.engine
                and existing.state
                in {
                    BrowserSessionState.STARTING,
                    BrowserSessionState.ACTIVE,
                    BrowserSessionState.USER_TAKEOVER,
                }
            ):
                raise BrowserSessionStateError(
                    f"Browser profile {command.profile_name} is already in use"
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
            allowed_origins=sorted(allowed_origins),
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
                    "allowed_origins": sorted(allowed_origins),
                    "headless": record.headless,
                },
            )
            observation = BrowserObservation.model_validate(result)
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
        saved = self._repository.save_observation(session_id, record.state, observation)
        return _public_snapshot(saved)

    def execute_action(self, session_id: str, action: BrowserAction) -> BrowserActionResult:
        record = self._active_record(session_id)
        self._validate_action(record, action)
        result = self._worker.call(
            "execute",
            {"session_id": session_id, "action": action.model_dump(mode="json")},
            timeout_seconds=max(75, action.timeout_ms / 1_000 + 10),
        )
        observation = BrowserObservation.model_validate(result.get("observation"))
        attempts_value = result.get("attempts")
        action_result = BrowserActionResult(
            id=str(uuid4()),
            session_id=session_id,
            sequence=self._repository.next_action_sequence(session_id),
            action=action,
            verified=bool(result.get("verified")),
            attempts=attempts_value if isinstance(attempts_value, int) else 1,
            observation=observation,
            error=str(result["error"]) if result.get("error") else None,
            created_at=datetime.now(UTC),
        )
        self._repository.add_action(action_result)
        updated = self._record(session_id)
        self._save_checkpoint(updated, observation, pending_action=None)
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
        result = self._worker.call("observe", {"session_id": session_id})
        observation = BrowserObservation.model_validate(result)
        saved = self._repository.save_observation(
            session_id, BrowserSessionState.ACTIVE, observation
        )
        self._save_checkpoint(saved, observation, pending_action=None)
        return _public_snapshot(saved)

    def restart(self, session_id: str) -> BrowserSessionSnapshot:
        self._active_record(session_id, allow_takeover=True)
        result = self._worker.call("restart_session", {"session_id": session_id})
        observation = BrowserObservation.model_validate(result)
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

    def stage_encrypted_upload(
        self,
        session_id: str,
        *,
        version_id: str,
        encrypted_path: str,
        file_name: str,
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
        upload_dir.mkdir(parents=True, exist_ok=True)
        destination = upload_dir / safe_name
        plaintext = self._cipher.decrypt_bytes(
            source.read_text(encoding="ascii"),
            context=f"document:{version_id}:file",
        )
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
