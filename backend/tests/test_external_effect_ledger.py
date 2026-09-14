from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from job_apply_pro.domain.external_effects import (
    ExternalEffectAdmission,
    ExternalEffectKind,
    ExternalEffectStatus,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.external_effects import (
    ExternalEffectConsumedError,
    ExternalEffectService,
)
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.external_effect_repository import (
    ExternalEffectConflictError,
    ExternalEffectRepository,
)
from job_apply_pro.storage.models import ExternalEffectAttemptRow, ExternalEffectOperationRow


def _ledger(tmp_path: Path) -> tuple[ExternalEffectService, sessionmaker[Session]]:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'external-effects.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return (
        ExternalEffectService(
            ExternalEffectRepository(factory),
            SensitiveDataCipher(StaticKeyProvider(b"l" * 32)),
        ),
        factory,
    )


def _admit(
    service: ExternalEffectService,
    *,
    effect_key: str = "fixture-effect-1",
    subject_id: str = "browser-session-1",
    request: object | None = None,
    now: datetime | None = None,
) -> ExternalEffectAdmission:
    return service.admit(
        effect_key=effect_key,
        kind=ExternalEffectKind.BROWSER_ACTION,
        subject_type="browser_session",
        subject_id=subject_id,
        actor="desktop-user",
        request=request or {"kind": "CLICK", "target": "submit"},
        now=now,
    )


def test_confirmed_effect_is_committed_before_and_after_dispatch(tmp_path: Path) -> None:
    service, factory = _ledger(tmp_path)
    admission = _admit(service)
    service.require_fresh(admission)
    attempt = service.prepare_attempt(
        admission.operation.id,
        provider="browser-worker",
        target_code="CLICK",
        request={"kind": "CLICK", "target": "submit"},
    )
    dispatching = service.begin_dispatch(admission.operation.id, attempt.id)
    assert dispatching.operation.status is ExternalEffectStatus.DISPATCHING
    assert dispatching.attempts[0].status is ExternalEffectStatus.DISPATCHING
    with factory() as session:
        operation = session.get(ExternalEffectOperationRow, admission.operation.id)
        assert operation is not None
        assert operation.status == ExternalEffectStatus.DISPATCHING.value

    finished = service.finish(
        admission.operation.id,
        attempt.id,
        status=ExternalEffectStatus.CONFIRMED,
        result_reference=attempt.id,
        result={"verified": True, "page": "confirmation"},
    )
    assert finished.operation.status is ExternalEffectStatus.CONFIRMED
    assert finished.attempts[0].status is ExternalEffectStatus.CONFIRMED
    assert finished.operation.result_reference == attempt.id


def test_exact_claim_is_consumed_and_mismatched_reuse_fails(tmp_path: Path) -> None:
    service, _ = _ledger(tmp_path)
    first = _admit(service)
    replay = _admit(service)
    assert replay.created is False
    assert replay.operation.id == first.operation.id
    with pytest.raises(ExternalEffectConsumedError, match="PREPARED"):
        service.require_fresh(replay)
    with pytest.raises(ExternalEffectConflictError, match="different work"):
        _admit(service, request={"kind": "UPLOAD", "target": "resume"})


def test_concurrent_admission_has_exactly_one_creator(tmp_path: Path) -> None:
    service, _ = _ledger(tmp_path)

    def admit() -> bool:
        return _admit(service).created

    with ThreadPoolExecutor(max_workers=8) as executor:
        created = list(executor.map(lambda _index: admit(), range(8)))
    assert sum(created) == 1


def test_unresolved_subject_blocks_a_different_claim(tmp_path: Path) -> None:
    service, _ = _ledger(tmp_path)
    first = _admit(service)
    attempt = service.prepare_attempt(
        first.operation.id,
        provider="browser-worker",
        target_code="CLICK",
        request={"kind": "CLICK", "target": "submit"},
    )
    service.begin_dispatch(first.operation.id, attempt.id)
    service.finish(
        first.operation.id,
        attempt.id,
        status=ExternalEffectStatus.UNCERTAIN,
        error_code="POSTCONDITION_UNKNOWN",
    )
    with pytest.raises(ExternalEffectConflictError, match="owns this subject"):
        _admit(service, effect_key="fixture-effect-2")


def test_terminal_outcome_is_immutable_and_exact_replay_is_idempotent(tmp_path: Path) -> None:
    service, _ = _ledger(tmp_path)
    admission = _admit(service)
    attempt = service.prepare_attempt(
        admission.operation.id,
        provider="browser-worker",
        target_code="CLICK",
        request={"kind": "CLICK", "target": "submit"},
    )
    service.begin_dispatch(admission.operation.id, attempt.id)
    first = service.finish(
        admission.operation.id,
        attempt.id,
        status=ExternalEffectStatus.FAILED,
        error_code="PRECONDITION_REJECTED",
    )
    replay = service.finish(
        admission.operation.id,
        attempt.id,
        status=ExternalEffectStatus.FAILED,
        error_code="PRECONDITION_REJECTED",
    )
    assert replay == first
    with pytest.raises(ExternalEffectConflictError, match="immutable"):
        service.finish(
            admission.operation.id,
            attempt.id,
            status=ExternalEffectStatus.UNCERTAIN,
            error_code="POSTCONDITION_UNKNOWN",
        )


def test_known_attempt_can_continue_without_reopening_replay(tmp_path: Path) -> None:
    service, _ = _ledger(tmp_path)
    admission = service.admit(
        effect_key="fixture-ai-effect",
        kind=ExternalEffectKind.AI_COMPLETION,
        subject_type="ai_request",
        subject_id="request-1",
        actor="local-service",
        request={"prompt": "private"},
    )
    first = service.prepare_attempt(
        admission.operation.id,
        provider="provider-a",
        target_code="model-a",
        request={"prompt": "private"},
    )
    service.begin_dispatch(admission.operation.id, first.id)
    continued = service.finish(
        admission.operation.id,
        first.id,
        status=ExternalEffectStatus.CONFIRMED,
        result_reference=first.id,
        result={"schema_valid": False},
        input_tokens=10,
        output_tokens=2,
        cost_micros=7,
        continue_operation=True,
    )
    assert continued.operation.status is ExternalEffectStatus.PREPARED
    assert continued.attempts[0].status is ExternalEffectStatus.CONFIRMED
    second = service.prepare_attempt(
        admission.operation.id,
        provider="provider-b",
        target_code="model-b",
        request={"prompt": "private", "repair": True},
    )
    assert second.sequence == 2


def test_startup_recovery_marks_dispatching_effect_uncertain_without_io(tmp_path: Path) -> None:
    service, _ = _ledger(tmp_path)
    now = datetime(2026, 9, 14, tzinfo=UTC)
    admission = _admit(service, now=now)
    attempt = service.prepare_attempt(
        admission.operation.id,
        provider="browser-worker",
        target_code="CLICK",
        request={"kind": "CLICK", "target": "submit"},
        now=now,
    )
    service.begin_dispatch(admission.operation.id, attempt.id, now=now)
    assert service.recover_interrupted(now=now + timedelta(seconds=1)) == 1
    record = service.get(admission.operation.id)
    assert record is not None
    assert record.operation.status is ExternalEffectStatus.UNCERTAIN
    assert record.operation.error_code == "PROCESS_INTERRUPTED"
    assert record.attempts[0].status is ExternalEffectStatus.UNCERTAIN


def test_public_records_and_storage_do_not_reveal_raw_inputs(tmp_path: Path) -> None:
    service, factory = _ledger(tmp_path)
    private_key = "fixture-private-operation-key"
    private_value = "candidate-private-answer"
    admission = _admit(
        service,
        effect_key=private_key,
        request={"value": private_value, "url": "https://portal.invalid/private"},
    )
    public = service.list_public()
    serialized = public[0].model_dump_json()
    assert "fingerprint" not in serialized
    assert private_key not in serialized
    assert private_value not in serialized
    with factory() as session:
        operation = session.scalar(select(ExternalEffectOperationRow))
        assert operation is not None
        stored = " ".join(str(value) for value in vars(operation).values())
        assert private_key not in stored
        assert private_value not in stored
        assert operation.claim_fingerprint != private_key
        assert operation.request_fingerprint != private_value
        assert session.scalar(select(ExternalEffectAttemptRow)) is None
    assert admission.operation.claim_fingerprint not in serialized


def test_keyed_fingerprint_preserves_exact_input_bytes() -> None:
    cipher = SensitiveDataCipher(StaticKeyProvider(b"k" * 32))
    assert cipher.keyed_fingerprint(b"Value", context="test") != cipher.keyed_fingerprint(
        b"value", context="test"
    )
    assert cipher.keyed_fingerprint(b"value", context="one") != cipher.keyed_fingerprint(
        b"value", context="two"
    )
