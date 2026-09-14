import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import Engine, create_engine, event, func, select, text
from sqlalchemy.orm import Session

from job_apply_pro.domain.communications import (
    CalendarCreateFields,
    CalendarEventSnapshot,
    CalendarMutationPlan,
    IntegrationProvider,
    MutationAudit,
    MutationKind,
    MutationStatus,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.models import (
    CalendarMutationClaimRow,
    CalendarMutationPlanRow,
    CommunicationMutationAuditRow,
)

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
CALENDAR_KINDS = [MutationKind.CREATE_CALENDAR_EVENT, MutationKind.UPDATE_CALENDAR_EVENT]


@pytest.fixture
def cipher() -> SensitiveDataCipher:
    return SensitiveDataCipher(StaticKeyProvider(b"c" * 32))


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database = create_engine(f"sqlite:///{(tmp_path / 'calendar-claims.db').as_posix()}")

    def foreign_keys(connection: sqlite3.Connection, _record: object) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    event.listen(database, "connect", foreign_keys)
    Base.metadata.create_all(database)
    try:
        yield database
    finally:
        database.dispose()


def _plan(plan_id: str = "calendar-plan") -> CalendarMutationPlan:
    return CalendarMutationPlan(
        id=plan_id,
        provider=IntegrationProvider.GOOGLE_CALENDAR,
        event=CalendarCreateFields(
            title="Synthetic interview",
            start_at=NOW,
            end_at=NOW + timedelta(hours=1),
            time_zone="UTC",
        ),
        kind=MutationKind.CREATE_CALENDAR_EVENT,
        fingerprint="a" * 64,
        created_at=NOW,
        policy_version="calendar-attempt-v1",
        wire_contract_version="calendar-create-wire-v1",
        account_key="b" * 64,
        account_label="candidate@example.test",
        provider_binding_fingerprint="c" * 64,
        calendar_target="PRIMARY",
        id_assignment="PROVIDER_NATIVE_DEDUPLICATED",
        provider_dedupe_policy="NATIVE_ATTEMPT_KEY_V1",
    )


def _audit(
    audit_id: str = "calendar-audit",
    *,
    plan_id: str = "calendar-plan",
    kind: MutationKind = MutationKind.CREATE_CALENDAR_EVENT,
    status: MutationStatus = MutationStatus.PLANNED,
    occurred_at: datetime = NOW,
) -> MutationAudit:
    return MutationAudit(
        id=audit_id,
        kind=kind,
        provider=IntegrationProvider.GOOGLE_CALENDAR,
        resource_id=plan_id,
        idempotency_key=f"confirmation-{audit_id}",
        fingerprint="a" * 64,
        status=status,
        confirmed_by="synthetic-review",
        occurred_at=occurred_at,
    )


def test_modern_calendar_binding_is_encrypted_and_roundtrips(
    engine: Engine, cipher: SensitiveDataCipher
) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        plan = repository.save_calendar_plan(_plan())
        row = session.get(CalendarMutationPlanRow, plan.id)
        assert row is not None
        assert "candidate@example.test" not in row.encrypted_payload
        payload = cipher.decrypt_json(
            row.encrypted_payload, context=f"calendar-plan:{plan.id}:payload"
        )
        assert payload["policy_version"] == "calendar-attempt-v1"
        assert payload["wire_contract_version"] == "calendar-create-wire-v1"
        event_payload = payload["event"]
        assert isinstance(event_payload, dict)
        assert event_payload["reminder_policy"] == "NONE"
        assert event_payload["visibility_policy"] == "PRIVATE"
        assert event_payload["availability_policy"] == "BUSY"
        assert payload["account_key"] == "b" * 64
        assert payload["account_label"] == "candidate@example.test"
        assert payload["provider_binding_fingerprint"] == "c" * 64
        assert payload["calendar_target"] == "PRIMARY"
        assert payload["id_assignment"] == "PROVIDER_NATIVE_DEDUPLICATED"
        assert payload["provider_dedupe_policy"] == "NATIVE_ATTEMPT_KEY_V1"
        assert "provider_event_id" not in plan.event.model_dump(mode="json")
        loaded = repository.get_calendar_plan(plan.id)
        assert loaded == plan
        assert loaded is not None and loaded.provider_binding_fingerprint == "c" * 64
        assert "provider_binding_fingerprint" not in loaded.model_dump(mode="json")


@pytest.mark.parametrize("kind", CALENDAR_KINDS)
def test_legacy_calendar_payload_is_read_without_identity_backfill(
    engine: Engine, cipher: SensitiveDataCipher, kind: MutationKind
) -> None:
    with Session(engine) as session:
        plan = _plan()
        legacy_event = CalendarEventSnapshot.model_validate(
            {
                **plan.event.model_dump(
                    mode="json",
                    exclude={
                        "attendee_notification_policy",
                        "reminder_policy",
                        "visibility_policy",
                        "availability_policy",
                    },
                ),
                "provider_event_id": "legacy-event",
            }
        )
        legacy = cipher.encrypt_json(
            {
                "event": legacy_event.model_dump(mode="json"),
                "prior_event": legacy_event.model_dump(mode="json")
                if kind is MutationKind.UPDATE_CALENDAR_EVENT
                else None,
            },
            context=f"calendar-plan:{plan.id}:payload",
        )
        session.add(
            CalendarMutationPlanRow(
                id=plan.id,
                provider=plan.provider.value,
                kind=kind.value,
                fingerprint=plan.fingerprint,
                encrypted_payload=legacy,
                created_at=NOW,
            )
        )
        session.commit()
        loaded = CommunicationRepository(session, cipher).get_calendar_plan(plan.id)
        assert loaded is not None
        assert loaded.policy_version is None and loaded.account_key is None
        assert loaded.account_label is None and loaded.provider_binding_fingerprint is None
        assert loaded.calendar_target is None
        assert loaded.id_assignment is None
        assert loaded.wire_contract_version is None
        assert loaded.provider_dedupe_policy is None
        assert loaded.kind is kind and loaded.event == legacy_event
        assert loaded.prior_event == (
            legacy_event if kind is MutationKind.UPDATE_CALENDAR_EVENT else None
        )
        row = session.get(CalendarMutationPlanRow, plan.id)
        assert row is not None and row.encrypted_payload == legacy


@pytest.mark.parametrize("kind", CALENDAR_KINDS)
def test_calendar_claim_atomically_persists_audit_and_blocks_new_keys(
    engine: Engine, cipher: SensitiveDataCipher, kind: MutationKind
) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        repository.save_calendar_plan(_plan())
        audit = _audit(kind=kind)
        assert repository.claim_calendar_mutation(audit) == (audit, True)
        claim = session.get(CalendarMutationClaimRow, audit.resource_id)
        assert claim is not None and claim.audit_id == audit.id
        assert repository.claim_calendar_mutation(_audit("another-key", kind=kind)) == (
            audit,
            False,
        )
        assert repository.list_audits() == [audit]


@pytest.mark.parametrize("kind", CALENDAR_KINDS)
@pytest.mark.parametrize("status", list(MutationStatus))
def test_every_unclaimed_legacy_calendar_audit_status_fails_closed(
    engine: Engine, cipher: SensitiveDataCipher, kind: MutationKind, status: MutationStatus
) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        repository.save_calendar_plan(_plan())
        prior = repository.add_audit(_audit(kind=kind, status=status))
        assert session.get(CalendarMutationClaimRow, prior.resource_id) is None
        assert repository.find_calendar_audit(prior.resource_id) is None
        with pytest.raises(ValueError, match="history is unclaimed"):
            repository.claim_calendar_mutation(_audit("new-request"))
        assert repository.list_audits() == [prior]
        assert session.get(CalendarMutationClaimRow, prior.resource_id) is None


def test_claim_join_selects_migration_chosen_oldest_and_preserves_all_history(
    engine: Engine, cipher: SensitiveDataCipher
) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        repository.save_calendar_plan(_plan())
        audits = [
            _audit("latest", occurred_at=NOW + timedelta(days=1)),
            _audit("b-earliest", status=MutationStatus.CONFIRMED),
            _audit("a-earliest", status=MutationStatus.FAILED),
            _audit(
                "mail-earlier", kind=MutationKind.SEND_MESSAGE, occurred_at=NOW - timedelta(days=1)
            ),
        ]
        for audit in audits:
            repository.add_audit(audit)
        session.add(CalendarMutationClaimRow(plan_id="calendar-plan", audit_id="a-earliest"))
        session.commit()
        assert repository.find_calendar_audit("calendar-plan") == audits[2]
        assert repository.claim_calendar_mutation(_audit("new-key")) == (audits[2], False)
        assert {audit.id for audit in repository.list_audits()} == {audit.id for audit in audits}


def test_calendar_terminal_transition_is_compare_and_swap_and_immutable(
    engine: Engine, cipher: SensitiveDataCipher
) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        repository.save_calendar_plan(_plan())
        planned = _audit()
        assert repository.claim_calendar_mutation(planned) == (planned, True)
        terminal = planned.model_copy(
            update={
                "status": MutationStatus.CONFIRMED,
                "provider_resource_id": "provider-event",
                "occurred_at": NOW + timedelta(seconds=1),
            }
        )
        assert repository.finish_calendar_mutation(terminal) == terminal
        assert repository.finish_calendar_mutation(terminal) == terminal
        with pytest.raises(ValueError, match="could not be recorded"):
            repository.finish_calendar_mutation(
                terminal.model_copy(
                    update={
                        "status": MutationStatus.UNCERTAIN,
                        "provider_resource_id": None,
                        "error_code": "ProviderCalendarUncertainError",
                    }
                )
            )
        with pytest.raises(ValueError, match="immutable terminal transition"):
            repository.add_audit(
                terminal.model_copy(
                    update={"status": MutationStatus.FAILED, "provider_resource_id": None}
                )
            )
        assert repository.find_calendar_audit(planned.resource_id) == terminal


def test_calendar_terminal_transition_requires_exact_atomic_claim(
    engine: Engine, cipher: SensitiveDataCipher
) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        repository.save_calendar_plan(_plan())
        planned = repository.add_audit(_audit())
        terminal = planned.model_copy(
            update={
                "status": MutationStatus.CONFIRMED,
                "provider_resource_id": "provider-event",
                "occurred_at": NOW + timedelta(seconds=1),
            }
        )
        with pytest.raises(ValueError, match="could not be recorded"):
            repository.finish_calendar_mutation(terminal)
        assert repository.find_audit_by_idempotency(planned.idempotency_key) == planned
        assert session.get(CalendarMutationClaimRow, planned.resource_id) is None


def test_calendar_terminal_transition_atomically_rechecks_claimed_plan_identity(
    engine: Engine, cipher: SensitiveDataCipher
) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        repository.save_calendar_plan(_plan())
        planned = _audit()
        assert repository.claim_calendar_mutation(planned) == (planned, True)
        row = session.get(CalendarMutationPlanRow, planned.resource_id)
        assert row is not None
        row.fingerprint = "b" * 64
        session.commit()
        terminal = planned.model_copy(
            update={
                "status": MutationStatus.CONFIRMED,
                "provider_resource_id": "provider-event",
                "occurred_at": NOW + timedelta(seconds=1),
            }
        )
        with pytest.raises(ValueError, match="could not be recorded"):
            repository.finish_calendar_mutation(terminal)
        assert repository.find_audit_by_idempotency(planned.idempotency_key) == planned


def test_claim_insert_failure_rolls_back_already_flushed_audit(
    engine: Engine, cipher: SensitiveDataCipher
) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        repository.save_calendar_plan(_plan())
        session.execute(
            text(
                "CREATE TRIGGER reject_calendar_claim BEFORE INSERT ON calendar_mutation_claims "
                "BEGIN SELECT RAISE(ABORT, 'synthetic claim failure'); END"
            )
        )
        session.commit()
        with pytest.raises(ValueError, match="could not be verified"):
            repository.claim_calendar_mutation(_audit())
        assert repository.list_audits() == []
        assert session.scalar(select(func.count()).select_from(CalendarMutationClaimRow)) == 0
        session.execute(text("DROP TRIGGER reject_calendar_claim"))
        session.commit()
        assert repository.claim_calendar_mutation(_audit()) == (_audit(), True)


def test_missing_plan_foreign_key_rolls_back_audit(
    engine: Engine, cipher: SensitiveDataCipher
) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        with pytest.raises(ValueError, match="could not be verified"):
            repository.claim_calendar_mutation(_audit())
        assert repository.list_audits() == []
        assert session.scalar(select(func.count()).select_from(CalendarMutationClaimRow)) == 0


@pytest.mark.parametrize("kind", list(MutationKind))
def test_existing_idempotency_key_for_another_mutation_never_wins_a_claim(
    engine: Engine, cipher: SensitiveDataCipher, kind: MutationKind
) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        repository.save_calendar_plan(_plan())
        prior = repository.add_audit(_audit("existing", plan_id="other-resource", kind=kind))
        contender = _audit("contender").model_copy(
            update={"idempotency_key": prior.idempotency_key}
        )
        assert repository.claim_calendar_mutation(contender) == (prior, False)
        assert repository.list_audits() == [prior]
        assert session.get(CalendarMutationClaimRow, contender.resource_id) is None


@pytest.mark.parametrize(
    "status", [value for value in MutationStatus if value is not MutationStatus.PLANNED]
)
def test_calendar_claim_requires_planned_status(
    engine: Engine, cipher: SensitiveDataCipher, status: MutationStatus
) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        with pytest.raises(ValueError, match="Invalid calendar"):
            repository.claim_calendar_mutation(_audit(status=status))
        assert repository.list_audits() == []


def test_calendar_claim_rejects_mail_kind(engine: Engine, cipher: SensitiveDataCipher) -> None:
    with Session(engine) as session:
        repository = CommunicationRepository(session, cipher)
        with pytest.raises(ValueError, match="Invalid calendar"):
            repository.claim_calendar_mutation(_audit(kind=MutationKind.SEND_MESSAGE))
        assert repository.list_audits() == []


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_sessions_only_one_calendar_attempt_wins(
    engine: Engine, cipher: SensitiveDataCipher, same_key: bool
) -> None:
    with Session(engine) as session:
        CommunicationRepository(session, cipher).save_calendar_plan(_plan())
    barrier = Barrier(2)

    class SimultaneousRepository(CommunicationRepository):
        synchronized = False

        def find_calendar_audit(self, plan_id: str) -> MutationAudit | None:
            prior = super().find_calendar_audit(plan_id)
            if not self.synchronized:
                self.synchronized = True
                barrier.wait(timeout=5)
            return prior

    def claim(index: int) -> tuple[MutationAudit, bool]:
        with Session(engine) as session:
            contender = _audit(f"race-{index}")
            if same_key:
                contender = contender.model_copy(update={"idempotency_key": "same-confirmation"})
            return SimultaneousRepository(session, cipher).claim_calendar_mutation(contender)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, [1, 2]))
    assert sum(won for _audit_result, won in results) == 1
    assert results[0][0] == results[1][0]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CommunicationMutationAuditRow)) == 1
        assert session.scalar(select(func.count()).select_from(CalendarMutationClaimRow)) == 1
