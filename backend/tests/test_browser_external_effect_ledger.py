import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from job_apply_pro.api.routes import browser as browser_routes
from job_apply_pro.browser.client import BrowserWorkerUnavailableError
from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionKind,
    BrowserControlKind,
    BrowserEngine,
    BrowserFieldReconciliationApproval,
    BrowserNavigationReconciliationApproval,
    BrowserObservation,
    BrowserObservedControl,
    BrowserRetryPolicy,
    BrowserSessionRecord,
    BrowserSessionState,
    BrowserSubmissionReconciliationApproval,
    BrowserUploadReconciliationApproval,
    BrowserVerification,
    ConfirmationState,
    LocatorStrategy,
    SemanticLocator,
    VerificationKind,
)
from job_apply_pro.domain.external_effects import ExternalEffectKind, ExternalEffectStatus
from job_apply_pro.domain.workbench import WorkflowRunSnapshot
from job_apply_pro.domain.workflow import TransitionCommand, WorkflowState
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.browser_runtime import (
    BrowserActionUncertainError,
    BrowserPolicyError,
    BrowserRuntimeService,
    BrowserSessionStateError,
)
from job_apply_pro.services.external_effects import ExternalEffectService
from job_apply_pro.storage.external_effect_repository import ExternalEffectRepository
from job_apply_pro.storage.repositories import BrowserRuntimeRepository, CheckpointRepository


def _observation() -> BrowserObservation:
    return BrowserObservation(
        sequence=1,
        url="http://127.0.0.1/form",
        title="Fixture",
        origin="http://127.0.0.1",
        page_type="FORM",
        page_fingerprint="fixture-page-v1",
        tabs=[],
        accessibility_snapshot="",
        visible_text="Fixture",
        controls=[],
        validation_errors=[],
        modals=[],
        console_errors=[],
        network_failures=[],
        upload_status=[],
        download_status=[],
        screenshot_path="fixture.png",
        observed_at=datetime.now(UTC),
    )


class _Workbench:
    def __init__(self) -> None:
        self.snapshot = WorkflowRunSnapshot(
            workflow_id="workflow-ledger",
            application_id="application-ledger",
            profile_id="profile-ledger",
            candidate_display_name="Fixture User",
            employer="Fixture",
            title="Engineer",
            state=WorkflowState.APPLICATION_OPENED,
            progress=40,
            updated_at=datetime.now(UTC),
            events=[],
        )

    def get_snapshot(self, workflow_id: str) -> WorkflowRunSnapshot | None:
        return self.snapshot if workflow_id == self.snapshot.workflow_id else None

    def list_snapshots(self) -> list[WorkflowRunSnapshot]:
        return [self.snapshot]

    def apply_transition(self, workflow_id: str, command: TransitionCommand) -> WorkflowRunSnapshot:
        del workflow_id, command
        raise NotImplementedError


class _Worker:
    def __init__(self, result: dict[str, object] | Exception) -> None:
        self.result = result
        self.calls = 0
        self.verification_result: dict[str, object] | Exception | None = None
        self.methods: list[str] = []

    @property
    def running(self) -> bool:
        return True

    def call(
        self,
        method: str,
        params: dict[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        del params, timeout_seconds
        self.calls += 1
        self.methods.append(method)
        outcome = self.verification_result if method == "verify_postcondition" else self.result
        if outcome is None:
            raise AssertionError(f"Unexpected worker method {method}")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _service(
    session: Session,
    tmp_path: Path,
    outcome: dict[str, object] | Exception,
    *,
    observation: BrowserObservation | None = None,
) -> tuple[BrowserRuntimeService, ExternalEffectService, _Worker]:
    now = datetime.now(UTC)
    observation = observation or _observation()
    BrowserRuntimeRepository(session).add(
        BrowserSessionRecord(
            id="00000000-0000-4000-8000-000000000101",
            workflow_id="workflow-ledger",
            engine=BrowserEngine.CHROMIUM,
            profile_name="ledger-fixture",
            state=BrowserSessionState.ACTIVE,
            current_url=observation.url,
            allowed_origins=[observation.origin],
            observation=observation,
            action_count=0,
            created_at=now,
            updated_at=now,
            user_data_dir=str(tmp_path / "browser"),
            artifact_dir=str(tmp_path / "artifacts"),
            headless=True,
        )
    )
    cipher = SensitiveDataCipher(StaticKeyProvider(b"e" * 32))
    effects = ExternalEffectService(
        ExternalEffectRepository(sessionmaker(bind=session.get_bind(), expire_on_commit=False)),
        cipher,
    )
    worker = _Worker(outcome)
    return (
        BrowserRuntimeService(
            BrowserRuntimeRepository(session),
            _Workbench(),
            CheckpointRepository(session),
            cipher,
            worker,
            effects,
            browser_data_dir=tmp_path / "browser",
            browser_artifact_dir=tmp_path / "artifacts",
            default_headless=True,
            automation_enabled=False,
        ),
        effects,
        worker,
    )


def _action() -> BrowserAction:
    return BrowserAction(
        kind=BrowserActionKind.SCREENSHOT,
        intended_result="Capture the reviewed fixture",
        verification=BrowserVerification(),
    )


def _field_action() -> BrowserAction:
    locator = SemanticLocator(
        strategy=LocatorStrategy.LABEL,
        value="Full name",
        exact=True,
    )
    return BrowserAction(
        kind=BrowserActionKind.FILL,
        locator=locator,
        value="Fixture Candidate",
        preconditions=[BrowserVerification(kind=VerificationKind.LOCATOR_VISIBLE, locator=locator)],
        intended_result="Populate one explicitly approved application field",
        verification=BrowserVerification(
            kind=VerificationKind.VALUE_EQUALS,
            locator=locator,
            value="Fixture Candidate",
        ),
        permission="ELEVATED",
        confirmation=ConfirmationState.CONFIRMED,
        sensitive_value=True,
    )


def _greenhouse_observation(
    *,
    page_type: str,
    page_fingerprint: str,
    include_navigation: bool,
) -> BrowserObservation:
    locator = SemanticLocator(
        strategy=LocatorStrategy.LABEL,
        value="Continue",
        exact=True,
    )
    controls = (
        [
            BrowserObservedControl(
                index=0,
                control_key="greenhouse-continue",
                kind=BrowserControlKind.BUTTON,
                tag="button",
                label="Continue",
                label_source="TEXT",
                text="Continue",
                visible=True,
                locator=locator,
            )
        ]
        if include_navigation
        else []
    )
    return BrowserObservation(
        sequence=1,
        url="https://boards.greenhouse.io/example/jobs/123",
        title="Synthetic Greenhouse fixture",
        origin="https://boards.greenhouse.io",
        page_type=page_type,
        page_fingerprint=page_fingerprint,
        tabs=[],
        accessibility_snapshot="",
        visible_text="Synthetic fixture",
        controls=controls,
        validation_errors=[],
        modals=[],
        console_errors=[],
        network_failures=[],
        upload_status=[],
        download_status=[],
        screenshot_path="fixture.png",
        observed_at=datetime.now(UTC),
    )


def _navigation_action() -> BrowserAction:
    locator = SemanticLocator(
        strategy=LocatorStrategy.LABEL,
        value="Continue",
        exact=True,
    )
    return BrowserAction(
        kind=BrowserActionKind.CLICK,
        locator=locator,
        preconditions=[BrowserVerification(kind=VerificationKind.LOCATOR_VISIBLE, locator=locator)],
        intended_result="Advance the exact reviewed Greenhouse form by one control",
        verification=BrowserVerification(kind=VerificationKind.NONE),
        permission="ELEVATED",
        confirmation=ConfirmationState.CONFIRMED,
    )


def _exact_url_navigation_action(
    target_url: str = "http://127.0.0.1/results",
) -> BrowserAction:
    return BrowserAction(
        kind=BrowserActionKind.NAVIGATE,
        url=target_url,
        intended_result="Navigate to the reviewed results page",
        verification=BrowserVerification(
            kind=VerificationKind.URL_EQUALS,
            value=target_url,
        ),
    )


def _exact_url_navigation_result(
    *,
    target_url: str = "http://127.0.0.1/results",
    page_fingerprint: str = "fixture-results-v2",
) -> BrowserObservation:
    return _observation().model_copy(
        update={
            "sequence": 2,
            "url": target_url,
            "page_type": "RESULTS",
            "page_fingerprint": page_fingerprint,
            "previous_action": BrowserActionKind.NAVIGATE.value,
        }
    )


def _greenhouse_upload_observation(
    *,
    page_fingerprint: str,
    upload_status: list[str],
    satisfied: bool,
) -> BrowserObservation:
    locator = SemanticLocator(
        strategy=LocatorStrategy.LABEL,
        value="Resume",
        exact=True,
    )
    return BrowserObservation(
        sequence=1,
        url="https://boards.greenhouse.io/example/jobs/123",
        title="Synthetic Greenhouse document fixture",
        origin="https://boards.greenhouse.io",
        page_type="DOCUMENT_UPLOAD",
        page_fingerprint=page_fingerprint,
        tabs=[],
        accessibility_snapshot="",
        visible_text="Upload resume",
        controls=[
            BrowserObservedControl(
                index=0,
                control_key="greenhouse-resume",
                kind=BrowserControlKind.FILE_UPLOAD,
                tag="input",
                input_type="file",
                label="Resume",
                label_source="LABEL",
                accept=".pdf,.doc,.docx",
                required=True,
                native_required=True,
                visible=True,
                will_validate=True,
                constraint_satisfied=satisfied,
                locator=locator,
            )
        ],
        validation_errors=[],
        modals=[],
        console_errors=[],
        network_failures=[],
        upload_status=upload_status,
        download_status=[],
        screenshot_path="fixture.png",
        observed_at=datetime.now(UTC),
    )


def _upload_action(path: Path) -> BrowserAction:
    locator = SemanticLocator(
        strategy=LocatorStrategy.LABEL,
        value="Resume",
        exact=True,
    )
    return BrowserAction(
        kind=BrowserActionKind.UPLOAD,
        locator=locator,
        file_path=str(path),
        preconditions=[BrowserVerification(kind=VerificationKind.LOCATOR_VISIBLE, locator=locator)],
        intended_result="Upload the exact reviewed immutable application document",
        verification=BrowserVerification(kind=VerificationKind.NONE),
        permission="ELEVATED",
        confirmation=ConfirmationState.CONFIRMED,
        sensitive_value=True,
    )


def _greenhouse_submission_observation(
    *,
    page_fingerprint: str = "greenhouse-review-v1",
) -> BrowserObservation:
    locator = SemanticLocator(
        strategy=LocatorStrategy.ROLE,
        value="button",
        name="Submit application",
        exact=True,
    )
    return BrowserObservation(
        sequence=1,
        url="https://boards.greenhouse.io/example/jobs/123#review",
        title="Synthetic Greenhouse submission review",
        origin="https://boards.greenhouse.io",
        page_type="SUBMISSION_REVIEW",
        page_fingerprint=page_fingerprint,
        tabs=[],
        accessibility_snapshot="",
        visible_text="Greenhouse review application",
        controls=[
            BrowserObservedControl(
                index=0,
                control_key="greenhouse-submit",
                kind=BrowserControlKind.BUTTON,
                tag="button",
                input_type="submit",
                text="Submit application",
                visible=True,
                locator=locator,
            )
        ],
        validation_errors=[],
        modals=[],
        console_errors=[],
        network_failures=[],
        upload_status=["candidate-resume.pdf"],
        download_status=[],
        screenshot_path="fixture.png",
        observed_at=datetime.now(UTC),
    )


def _greenhouse_confirmation_observation(
    *,
    page_fingerprint: str = "greenhouse-confirmation-v2",
    visible_text: str = ("Greenhouse application received. Confirmation number GH-12345"),
) -> BrowserObservation:
    return BrowserObservation(
        sequence=2,
        url="https://boards.greenhouse.io/example/jobs/123/confirmation",
        title="Synthetic Greenhouse confirmation",
        origin="https://boards.greenhouse.io",
        page_type="CONFIRMATION",
        page_fingerprint=page_fingerprint,
        tabs=[],
        accessibility_snapshot="",
        visible_text=visible_text,
        controls=[],
        validation_errors=[],
        modals=[],
        console_errors=[],
        network_failures=[],
        upload_status=["candidate-resume.pdf"],
        download_status=[],
        screenshot_path="fixture.png",
        observed_at=datetime.now(UTC),
    )


def _submission_action() -> BrowserAction:
    locator = SemanticLocator(
        strategy=LocatorStrategy.ROLE,
        value="button",
        name="Submit application",
        exact=True,
    )
    return BrowserAction(
        kind=BrowserActionKind.CLICK,
        locator=locator,
        preconditions=[
            BrowserVerification(
                kind=VerificationKind.LOCATOR_VISIBLE,
                locator=locator,
            )
        ],
        intended_result="Submit the exact reviewed application",
        verification=BrowserVerification(kind=VerificationKind.NONE),
        permission="ELEVATED",
        confirmation=ConfirmationState.CONFIRMED,
    )


def test_upload_staging_requires_exact_reviewed_plaintext_sha256(
    session: Session, tmp_path: Path
) -> None:
    service, _, worker = _service(session, tmp_path, RuntimeError("unused"))
    version_id = "version-reviewed"
    plaintext = b"synthetic immutable resume bytes"
    document_dir = tmp_path / "documents"
    document_dir.mkdir()
    encrypted = document_dir / "resume.enc"
    cipher = SensitiveDataCipher(StaticKeyProvider(b"e" * 32))
    encrypted.write_text(
        cipher.encrypt_bytes(plaintext, context=f"document:{version_id}:file"),
        encoding="ascii",
    )

    with pytest.raises(BrowserPolicyError, match="do not match"):
        service.stage_encrypted_upload(
            "00000000-0000-4000-8000-000000000101",
            version_id=version_id,
            encrypted_path=str(encrypted),
            file_name="candidate-resume.pdf",
            expected_sha256="0" * 64,
        )
    assert not (tmp_path / "artifacts" / "staged-uploads").exists()

    staged = service.stage_encrypted_upload(
        "00000000-0000-4000-8000-000000000101",
        version_id=version_id,
        encrypted_path=str(encrypted),
        file_name="candidate-resume.pdf",
        expected_sha256=hashlib.sha256(plaintext).hexdigest(),
    )
    assert Path(staged).read_bytes() == plaintext
    service.clear_staged_uploads("00000000-0000-4000-8000-000000000101")
    assert not Path(staged).exists()
    assert worker.calls == 0


def test_confirmed_worker_result_uses_attempt_as_action_identity(
    session: Session, tmp_path: Path
) -> None:
    observation = _observation()
    service, effects, worker = _service(
        session,
        tmp_path,
        {
            "disposition": "CONFIRMED",
            "verified": True,
            "attempts": 1,
            "observation": observation.model_dump(mode="json"),
            "error_code": None,
        },
    )

    result = service.execute_action("00000000-0000-4000-8000-000000000101", _action())

    record = effects.get(effects.list_public()[0].id)
    assert record is not None
    assert worker.calls == 1
    assert result.id == record.attempts[0].id
    assert record.operation.status is ExternalEffectStatus.CONFIRMED
    assert record.operation.result_reference == f"browser-action:{result.id}"
    assert service.list_actions(result.session_id)[0].id == result.id


def test_known_precondition_failure_is_terminal_without_takeover(
    session: Session, tmp_path: Path
) -> None:
    observation = _observation()
    service, effects, worker = _service(
        session,
        tmp_path,
        {
            "disposition": "NOT_APPLIED",
            "verified": False,
            "attempts": 1,
            "observation": observation.model_dump(mode="json"),
            "error_code": "PRECONDITION_FAILED",
        },
    )

    result = service.execute_action("00000000-0000-4000-8000-000000000101", _action())

    assert worker.calls == 1
    assert not result.verified
    assert result.error == "PRECONDITION_FAILED"
    assert effects.list_public()[0].status is ExternalEffectStatus.FAILED
    assert service.get_session(result.session_id).state is BrowserSessionState.ACTIVE


def test_lost_worker_response_is_uncertain_and_blocks_resume(
    session: Session, tmp_path: Path
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("raw worker detail must not persist"),
    )
    session_id = "00000000-0000-4000-8000-000000000101"

    with pytest.raises(BrowserActionUncertainError, match="automatic retry is blocked"):
        service.execute_action(session_id, _action())

    assert worker.calls == 1
    assert effects.list_public()[0].status is ExternalEffectStatus.UNCERTAIN
    assert service.get_session(session_id).state is BrowserSessionState.USER_TAKEOVER
    assert service.list_actions(session_id)[0].error == "WORKER_RESPONSE_UNAVAILABLE"
    assert "raw worker detail" not in service.list_actions(session_id)[0].model_dump_json()
    assert effects.unresolved_subject_ids(
        kind=ExternalEffectKind.BROWSER_ACTION,
        subject_type="browser_session",
    ) == [session_id]
    with pytest.raises(BrowserSessionStateError, match="unresolved external action"):
        service.resume(session_id)
    with pytest.raises(BrowserSessionStateError, match="not active"):
        service.execute_action(session_id, _action())
    assert worker.calls == 1


def test_uncertain_field_is_reconciled_only_by_fresh_exact_postcondition(
    session: Session, tmp_path: Path
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _field_action())
    operation = effects.list_public()[0]
    assert operation.reconciliation_available
    stored_action = service.list_actions(session_id)[0]
    assert stored_action.action.value is None
    assert stored_action.action.verification.value is None

    observation = _observation()
    worker.verification_result = {
        "verified": True,
        "observation": observation.model_dump(mode="json"),
        "error_code": None,
    }
    preview = service.preview_field_reconciliation(session_id, operation.id)
    result = service.approve_field_reconciliation(
        session_id,
        BrowserFieldReconciliationApproval(
            operation_id=operation.id,
            expected_review_fingerprint=preview.review_fingerprint,
            confirmation_phrase="RECONCILE VERIFIED FIELD",
        ),
    )

    assert result.reconciliation_kind == "BROWSER_FIELD_VALUE_CONFIRMED"
    assert result.action_kind is BrowserActionKind.FILL
    assert worker.methods == ["execute", "verify_postcondition", "verify_postcondition"]
    assert not effects.has_unresolved_subject("browser_session", session_id)
    record = effects.get(operation.id)
    assert record is not None
    assert record.operation.status is ExternalEffectStatus.UNCERTAIN
    assert record.reconciliation is not None


def test_field_reconciliation_refuses_nonmatching_postcondition(
    session: Session, tmp_path: Path
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _field_action())
    operation = effects.list_public()[0]
    worker.verification_result = {
        "verified": False,
        "observation": _observation().model_dump(mode="json"),
        "error_code": "POSTCONDITION_NOT_OBSERVED",
    }

    with pytest.raises(BrowserSessionStateError, match="does not prove"):
        service.preview_field_reconciliation(session_id, operation.id)

    assert effects.has_unresolved_subject("browser_session", session_id)
    assert worker.methods == ["execute", "verify_postcondition"]


def test_field_reconciliation_approval_rechecks_and_refuses_changed_field(
    session: Session, tmp_path: Path
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _field_action())
    operation = effects.list_public()[0]
    worker.verification_result = {
        "verified": True,
        "observation": _observation().model_dump(mode="json"),
        "error_code": None,
    }
    preview = service.preview_field_reconciliation(session_id, operation.id)
    worker.verification_result = {
        "verified": False,
        "observation": _observation().model_dump(mode="json"),
        "error_code": "POSTCONDITION_NOT_OBSERVED",
    }

    with pytest.raises(BrowserSessionStateError, match="does not prove"):
        service.approve_field_reconciliation(
            session_id,
            BrowserFieldReconciliationApproval(
                operation_id=operation.id,
                expected_review_fingerprint=preview.review_fingerprint,
                confirmation_phrase="RECONCILE VERIFIED FIELD",
            ),
        )

    assert effects.has_unresolved_subject("browser_session", session_id)
    assert worker.methods == ["execute", "verify_postcondition", "verify_postcondition"]


def test_uncertain_non_field_action_has_no_reconciliation_authority(
    session: Session, tmp_path: Path
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _action())
    operation = effects.list_public()[0]

    assert not operation.reconciliation_available
    with pytest.raises(BrowserSessionStateError, match="not an available"):
        service.preview_field_reconciliation(session_id, operation.id)
    assert effects.has_unresolved_subject("browser_session", session_id)
    assert worker.methods == ["execute"]


def test_uncertain_navigation_is_reconciled_only_by_a_later_reviewed_stage(
    session: Session, tmp_path: Path
) -> None:
    source = _greenhouse_observation(
        page_type="APPLICATION_FORM",
        page_fingerprint="greenhouse-application-v1",
        include_navigation=True,
    )
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
        observation=source,
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _navigation_action())
    operation = effects.list_public()[0]
    assert operation.reconciliation_available
    assert operation.reconciliation_kind == "BROWSER_NAVIGATION_CONFIRMED"

    later = _greenhouse_observation(
        page_type="DOCUMENT_UPLOAD",
        page_fingerprint="greenhouse-documents-v2",
        include_navigation=False,
    )
    worker.result = later.model_dump(mode="json")
    preview = service.preview_navigation_reconciliation(session_id, operation.id)
    result = service.approve_navigation_reconciliation(
        session_id,
        BrowserNavigationReconciliationApproval(
            operation_id=operation.id,
            expected_review_fingerprint=preview.review_fingerprint,
            confirmation_phrase="RECONCILE REVIEWED NAVIGATION",
        ),
    )

    assert preview.source_page_type == "APPLICATION_FORM"
    assert preview.result_page_type == "DOCUMENT_UPLOAD"
    assert result.reconciliation_kind == "BROWSER_NAVIGATION_CONFIRMED"
    assert result.result_page_fingerprint == "greenhouse-documents-v2"
    assert worker.methods == ["execute", "observe", "observe"]
    assert not effects.has_unresolved_subject("browser_session", session_id)
    record = effects.get(operation.id)
    assert record is not None
    assert record.operation.status is ExternalEffectStatus.UNCERTAIN


@pytest.mark.parametrize(
    ("page_type", "page_fingerprint"),
    [
        ("APPLICATION_FORM", "greenhouse-application-v1"),
        ("CONFIRMATION", "greenhouse-confirmation-v2"),
    ],
)
def test_navigation_reconciliation_refuses_same_or_confirmation_stage(
    session: Session,
    tmp_path: Path,
    page_type: str,
    page_fingerprint: str,
) -> None:
    source = _greenhouse_observation(
        page_type="APPLICATION_FORM",
        page_fingerprint="greenhouse-application-v1",
        include_navigation=True,
    )
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
        observation=source,
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _navigation_action())
    operation = effects.list_public()[0]
    worker.result = _greenhouse_observation(
        page_type=page_type,
        page_fingerprint=page_fingerprint,
        include_navigation=False,
    ).model_dump(mode="json")

    with pytest.raises(BrowserSessionStateError, match="does not prove"):
        service.preview_navigation_reconciliation(session_id, operation.id)

    assert effects.has_unresolved_subject("browser_session", session_id)
    assert worker.methods == ["execute", "observe"]


def test_navigation_reconciliation_approval_rechecks_current_stage(
    session: Session, tmp_path: Path
) -> None:
    source = _greenhouse_observation(
        page_type="APPLICATION_FORM",
        page_fingerprint="greenhouse-application-v1",
        include_navigation=True,
    )
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
        observation=source,
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _navigation_action())
    operation = effects.list_public()[0]
    worker.result = _greenhouse_observation(
        page_type="DOCUMENT_UPLOAD",
        page_fingerprint="greenhouse-documents-v2",
        include_navigation=False,
    ).model_dump(mode="json")
    preview = service.preview_navigation_reconciliation(session_id, operation.id)
    worker.result = _greenhouse_observation(
        page_type="QUESTIONNAIRE",
        page_fingerprint="greenhouse-questionnaire-v3",
        include_navigation=False,
    ).model_dump(mode="json")

    with pytest.raises(BrowserSessionStateError, match="changed after review"):
        service.approve_navigation_reconciliation(
            session_id,
            BrowserNavigationReconciliationApproval(
                operation_id=operation.id,
                expected_review_fingerprint=preview.review_fingerprint,
                confirmation_phrase="RECONCILE REVIEWED NAVIGATION",
            ),
        )

    assert effects.has_unresolved_subject("browser_session", session_id)
    assert worker.methods == ["execute", "observe", "observe"]


def test_uncertain_exact_url_navigation_reconciles_without_replay(
    session: Session, tmp_path: Path
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _exact_url_navigation_action())
    operation = effects.list_public()[0]
    assert operation.reconciliation_available
    assert operation.reconciliation_kind == "BROWSER_NAVIGATION_CONFIRMED"
    prepared = effects.get(operation.id)
    assert prepared is not None
    assert prepared.reconciliation is not None
    payload = effects.browser_navigation_reconciliation_payload(prepared.reconciliation)
    assert payload == {
        "action_kind": "NAVIGATE",
        "navigation_scope": "EXACT_URL",
        "postcondition": "URL_EQUALS",
        "request_fingerprint": prepared.operation.request_fingerprint,
        "source_origin": "http://127.0.0.1",
        "source_page_type": "FORM",
        "source_url": "http://127.0.0.1/form",
        "target_origin": "http://127.0.0.1",
        "target_url": "http://127.0.0.1/results",
    }

    worker.result = _exact_url_navigation_result().model_dump(mode="json")
    preview = service.preview_navigation_reconciliation(session_id, operation.id)
    result = service.approve_navigation_reconciliation(
        session_id,
        BrowserNavigationReconciliationApproval(
            operation_id=operation.id,
            expected_review_fingerprint=preview.review_fingerprint,
            confirmation_phrase="RECONCILE REVIEWED NAVIGATION",
        ),
    )

    assert preview.navigation_scope == "EXACT_URL"
    assert preview.source_page_type == "FORM"
    assert preview.result_page_type == "RESULTS"
    assert result.navigation_scope == "EXACT_URL"
    assert result.result_page_fingerprint == "fixture-results-v2"
    assert worker.methods == ["execute", "observe", "observe"]
    assert not effects.has_unresolved_subject("browser_session", session_id)
    record = effects.get(operation.id)
    assert record is not None
    assert record.operation.status is ExternalEffectStatus.UNCERTAIN


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (
            _exact_url_navigation_result(target_url="http://127.0.0.1/other"),
            "exact reviewed navigation target",
        ),
        (
            _exact_url_navigation_result(page_fingerprint="fixture-page-v1"),
            "exact reviewed navigation target",
        ),
        (
            _exact_url_navigation_result().model_copy(update={"previous_action": "CLICK"}),
            "exact reviewed navigation target",
        ),
    ],
)
def test_exact_url_navigation_reconciliation_refuses_inexact_evidence(
    session: Session,
    tmp_path: Path,
    result: BrowserObservation,
    message: str,
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _exact_url_navigation_action())
    operation = effects.list_public()[0]
    worker.result = result.model_dump(mode="json")

    with pytest.raises(BrowserSessionStateError, match=message):
        service.preview_navigation_reconciliation(session_id, operation.id)

    assert effects.has_unresolved_subject("browser_session", session_id)
    assert worker.methods == ["execute", "observe"]


def test_exact_url_navigation_approval_rechecks_current_page(
    session: Session, tmp_path: Path
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _exact_url_navigation_action())
    operation = effects.list_public()[0]
    worker.result = _exact_url_navigation_result().model_dump(mode="json")
    preview = service.preview_navigation_reconciliation(session_id, operation.id)
    worker.result = _exact_url_navigation_result(page_fingerprint="fixture-results-v3").model_dump(
        mode="json"
    )

    with pytest.raises(BrowserSessionStateError, match="changed after review"):
        service.approve_navigation_reconciliation(
            session_id,
            BrowserNavigationReconciliationApproval(
                operation_id=operation.id,
                expected_review_fingerprint=preview.review_fingerprint,
                confirmation_phrase="RECONCILE REVIEWED NAVIGATION",
            ),
        )

    assert effects.has_unresolved_subject("browser_session", session_id)
    assert worker.methods == ["execute", "observe", "observe"]


def test_inexact_url_navigation_has_no_reconciliation_authority(
    session: Session, tmp_path: Path
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    action = _exact_url_navigation_action().model_copy(
        update={
            "verification": BrowserVerification(
                kind=VerificationKind.URL_CONTAINS,
                value="/results",
            )
        }
    )
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, action)
    operation = effects.list_public()[0]

    assert not operation.reconciliation_available
    with pytest.raises(BrowserSessionStateError, match="not an available"):
        service.preview_navigation_reconciliation(session_id, operation.id)
    assert worker.methods == ["execute"]


def test_exact_url_navigation_refuses_target_already_current(
    session: Session, tmp_path: Path
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("must not dispatch"),
    )
    session_id = "00000000-0000-4000-8000-000000000101"

    with pytest.raises(BrowserPolicyError, match="outside the reconciliation contract"):
        service.execute_action(
            session_id,
            _exact_url_navigation_action("http://127.0.0.1/form"),
        )

    assert effects.list_public() == []
    assert worker.methods == []


def test_uncertain_upload_is_reconciled_only_by_exact_new_filename(
    session: Session, tmp_path: Path
) -> None:
    source = _greenhouse_upload_observation(
        page_fingerprint="greenhouse-documents-v1",
        upload_status=[],
        satisfied=False,
    )
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
        observation=source,
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    staged = tmp_path / "artifacts" / "staged-uploads" / "candidate-resume.pdf"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"exact reviewed resume bytes")

    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _upload_action(staged))
    operation = effects.list_public()[0]
    assert operation.reconciliation_available
    assert operation.reconciliation_kind == "BROWSER_UPLOAD_CONFIRMED"
    stored_action = service.list_actions(session_id)[0]
    assert stored_action.action.file_path is None
    assert stored_action.error == "Sensitive browser action failed or could not be verified"
    service.clear_staged_uploads(session_id)

    result_observation = _greenhouse_upload_observation(
        page_fingerprint="greenhouse-documents-uploaded-v2",
        upload_status=["candidate-resume.pdf"],
        satisfied=True,
    )
    worker.result = result_observation.model_dump(mode="json")
    preview = service.preview_upload_reconciliation(session_id, operation.id)
    result = service.approve_upload_reconciliation(
        session_id,
        BrowserUploadReconciliationApproval(
            operation_id=operation.id,
            expected_review_fingerprint=preview.review_fingerprint,
            confirmation_phrase="RECONCILE REVIEWED UPLOAD",
        ),
    )

    assert preview.file_name == "candidate-resume.pdf"
    assert preview.page_type == "DOCUMENT_UPLOAD"
    assert result.reconciliation_kind == "BROWSER_UPLOAD_CONFIRMED"
    assert result.result_page_fingerprint == "greenhouse-documents-uploaded-v2"
    assert worker.methods == ["execute", "observe", "observe"]
    assert not effects.has_unresolved_subject("browser_session", session_id)
    record = effects.get(operation.id)
    assert record is not None
    assert record.operation.status is ExternalEffectStatus.UNCERTAIN


def test_reviewed_upload_outside_session_staging_has_no_reconciliation_authority(
    session: Session, tmp_path: Path
) -> None:
    source = _greenhouse_upload_observation(
        page_fingerprint="greenhouse-documents-v1",
        upload_status=[],
        satisfied=False,
    )
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("must not dispatch"),
        observation=source,
    )
    outside = tmp_path / "candidate-resume.pdf"
    outside.write_bytes(b"not in the exact session staging directory")

    with pytest.raises(BrowserPolicyError, match="outside the reconciliation contract"):
        service.execute_action("00000000-0000-4000-8000-000000000101", _upload_action(outside))

    assert effects.list_public() == []
    assert worker.methods == []


@pytest.mark.parametrize(
    ("page_fingerprint", "upload_status"),
    [
        ("greenhouse-documents-v1", ["candidate-resume.pdf"]),
        ("greenhouse-documents-uploaded-v2", []),
        ("greenhouse-documents-uploaded-v2", ["candidate-resume.pdf", "candidate-resume.pdf"]),
    ],
)
def test_upload_reconciliation_refuses_stale_absent_or_duplicate_filename(
    session: Session,
    tmp_path: Path,
    page_fingerprint: str,
    upload_status: list[str],
) -> None:
    source = _greenhouse_upload_observation(
        page_fingerprint="greenhouse-documents-v1",
        upload_status=[],
        satisfied=False,
    )
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
        observation=source,
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    staged = tmp_path / "artifacts" / "staged-uploads" / "candidate-resume.pdf"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"exact reviewed resume bytes")
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _upload_action(staged))
    operation = effects.list_public()[0]
    worker.result = _greenhouse_upload_observation(
        page_fingerprint=page_fingerprint,
        upload_status=upload_status,
        satisfied=bool(upload_status),
    ).model_dump(mode="json")

    with pytest.raises(BrowserSessionStateError, match="does not prove"):
        service.preview_upload_reconciliation(session_id, operation.id)

    assert effects.has_unresolved_subject("browser_session", session_id)
    assert worker.methods == ["execute", "observe"]


def test_upload_reconciliation_approval_rechecks_current_filename(
    session: Session, tmp_path: Path
) -> None:
    source = _greenhouse_upload_observation(
        page_fingerprint="greenhouse-documents-v1",
        upload_status=[],
        satisfied=False,
    )
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
        observation=source,
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    staged = tmp_path / "artifacts" / "staged-uploads" / "candidate-resume.pdf"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"exact reviewed resume bytes")
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _upload_action(staged))
    operation = effects.list_public()[0]
    worker.result = _greenhouse_upload_observation(
        page_fingerprint="greenhouse-documents-uploaded-v2",
        upload_status=["candidate-resume.pdf"],
        satisfied=True,
    ).model_dump(mode="json")
    preview = service.preview_upload_reconciliation(session_id, operation.id)
    worker.result = _greenhouse_upload_observation(
        page_fingerprint="greenhouse-documents-changed-v3",
        upload_status=["different-resume.pdf"],
        satisfied=True,
    ).model_dump(mode="json")

    with pytest.raises(BrowserSessionStateError, match="does not prove"):
        service.approve_upload_reconciliation(
            session_id,
            BrowserUploadReconciliationApproval(
                operation_id=operation.id,
                expected_review_fingerprint=preview.review_fingerprint,
                confirmation_phrase="RECONCILE REVIEWED UPLOAD",
            ),
        )

    assert effects.has_unresolved_subject("browser_session", session_id)
    assert worker.methods == ["execute", "observe", "observe"]


def test_uncertain_submission_is_reconciled_only_by_identifier_backed_confirmation(
    session: Session, tmp_path: Path
) -> None:
    source = _greenhouse_submission_observation()
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
        observation=source,
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _submission_action())
    operation = effects.list_public()[0]
    assert operation.reconciliation_available
    assert operation.reconciliation_kind == "BROWSER_SUBMISSION_CONFIRMED"

    worker.result = _greenhouse_confirmation_observation().model_dump(mode="json")
    preview = service.preview_submission_reconciliation(session_id, operation.id)
    result = service.approve_submission_reconciliation(
        session_id,
        BrowserSubmissionReconciliationApproval(
            operation_id=operation.id,
            expected_review_fingerprint=preview.review_fingerprint,
            confirmation_phrase="RECONCILE CONFIRMED SUBMISSION",
        ),
    )

    assert preview.source_page_type == "SUBMISSION_REVIEW"
    assert preview.result_page_type == "CONFIRMATION"
    assert result.reconciliation_kind == "BROWSER_SUBMISSION_CONFIRMED"
    assert result.result_page_fingerprint == "greenhouse-confirmation-v2"
    assert worker.methods == ["execute", "observe", "observe"]
    assert not effects.has_unresolved_subject("browser_session", session_id)
    record = effects.get(operation.id)
    assert record is not None
    assert record.operation.status is ExternalEffectStatus.UNCERTAIN
    assert record.attempts[0].status is ExternalEffectStatus.UNCERTAIN


@pytest.mark.parametrize(
    ("page_fingerprint", "visible_text"),
    [
        ("greenhouse-review-v1", "Greenhouse application received. Confirmation GH-12345"),
        ("greenhouse-confirmation-v2", "Greenhouse application received"),
        ("greenhouse-confirmation-v2", "Greenhouse confirmation number GH-12345"),
    ],
)
def test_submission_reconciliation_refuses_stale_or_unverified_confirmation(
    session: Session,
    tmp_path: Path,
    page_fingerprint: str,
    visible_text: str,
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
        observation=_greenhouse_submission_observation(),
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _submission_action())
    operation = effects.list_public()[0]
    worker.result = _greenhouse_confirmation_observation(
        page_fingerprint=page_fingerprint,
        visible_text=visible_text,
    ).model_dump(mode="json")

    with pytest.raises(BrowserSessionStateError, match="does not prove"):
        service.preview_submission_reconciliation(session_id, operation.id)

    assert effects.has_unresolved_subject("browser_session", session_id)
    assert worker.methods == ["execute", "observe"]


def test_submission_reconciliation_approval_rechecks_confirmation_identifier(
    session: Session, tmp_path: Path
) -> None:
    service, effects, worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("fixture response loss"),
        observation=_greenhouse_submission_observation(),
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    with pytest.raises(BrowserActionUncertainError):
        service.execute_action(session_id, _submission_action())
    operation = effects.list_public()[0]
    worker.result = _greenhouse_confirmation_observation().model_dump(mode="json")
    preview = service.preview_submission_reconciliation(session_id, operation.id)
    worker.result = _greenhouse_confirmation_observation(
        page_fingerprint="greenhouse-confirmation-v3",
        visible_text="Greenhouse application received. Confirmation number GH-67890",
    ).model_dump(mode="json")

    with pytest.raises(BrowserSessionStateError, match="changed after review"):
        service.approve_submission_reconciliation(
            session_id,
            BrowserSubmissionReconciliationApproval(
                operation_id=operation.id,
                expected_review_fingerprint=preview.review_fingerprint,
                confirmation_phrase="RECONCILE CONFIRMED SUBMISSION",
            ),
        )

    assert effects.has_unresolved_subject("browser_session", session_id)
    assert worker.methods == ["execute", "observe", "observe"]


def test_startup_recovery_marks_interrupted_browser_session_for_takeover(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, effects, _worker = _service(
        session,
        tmp_path,
        BrowserWorkerUnavailableError("unused"),
    )
    session_id = "00000000-0000-4000-8000-000000000101"
    request = _action().model_dump(mode="json")
    admission = effects.admit(
        effect_key="browser:startup-recovery:1",
        kind=ExternalEffectKind.BROWSER_ACTION,
        subject_type="browser_session",
        subject_id=session_id,
        actor="browser-runtime",
        request=request,
    )
    attempt = effects.prepare_attempt(
        admission.operation.id,
        provider="playwright",
        target_code="SCREENSHOT",
        request=request,
    )
    effects.begin_dispatch(admission.operation.id, attempt.id)
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(browser_routes, "SessionFactory", factory)

    recovered = browser_routes.recover_browser_external_effects(
        SensitiveDataCipher(StaticKeyProvider(b"e" * 32))
    )

    assert recovered == 1
    assert service.get_session(session_id).state is BrowserSessionState.USER_TAKEOVER
    record = effects.get(admission.operation.id)
    assert record is not None
    assert record.operation.status is ExternalEffectStatus.UNCERTAIN
    assert record.operation.error_code == "PROCESS_INTERRUPTED"


def test_startup_recovery_is_a_noop_before_ledger_migration(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    bind = session.get_bind()
    session.execute(text("DROP TABLE external_effect_attempts"))
    session.execute(text("DROP TABLE external_effect_operations"))
    session.commit()
    factory = sessionmaker(bind=bind, expire_on_commit=False)
    monkeypatch.setattr(browser_routes, "SessionFactory", factory)

    assert (
        browser_routes.recover_browser_external_effects(
            SensitiveDataCipher(StaticKeyProvider(b"e" * 32))
        )
        == 0
    )


def test_browser_retry_contract_rejects_more_than_one_attempt() -> None:
    with pytest.raises(ValidationError):
        BrowserRetryPolicy(max_attempts=2)
