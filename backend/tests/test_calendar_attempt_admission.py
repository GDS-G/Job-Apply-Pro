from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.communications import get_communication_service
from job_apply_pro.config import get_settings
from job_apply_pro.domain.communications import (
    CalendarCreateFields,
    CalendarEventSnapshot,
    CalendarMutationCreate,
    CalendarMutationPlan,
    IntegrationProvider,
    MutationAudit,
    MutationConfirmation,
    MutationKind,
    MutationStatus,
)
from job_apply_pro.integrations.communications import (
    FixtureCalendarProvider,
    ProviderCalendarNotAppliedError,
    ProviderCalendarUncertainError,
    ProviderMutationError,
)
from job_apply_pro.integrations.configuration import ProviderConnectionConfig
from job_apply_pro.main import create_app
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.communications import CommunicationService
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.models import (
    CalendarMutationClaimRow,
    CalendarMutationPlanRow,
    CommunicationMutationAuditRow,
)

PROVIDER = IntegrationProvider.GOOGLE_CALENDAR
WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class TrackingCalendar(FixtureCalendarProvider):
    def __init__(self) -> None:
        super().__init__(PROVIDER)
        self.calls = 0
        self.error: Exception | None = None
        self.invalid_result: object | None = None

    def create_event(self, event: CalendarCreateFields, *, idempotency_key: str) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.invalid_result is not None:
            return cast(str, self.invalid_result)
        return super().create_event(event, idempotency_key=idempotency_key)


def _cipher() -> SensitiveDataCipher:
    return SensitiveDataCipher(StaticKeyProvider(b"c" * 32))


def _service(
    session: Session,
    *,
    adapter: TrackingCalendar | None = None,
    identity: str | None = "synthetic-calendar-account",
    epoch: str | None = "synthetic-calendar-epoch",
    label: str = "candidate@example.test",
    write: bool = True,
    scopes: list[str] | None = None,
) -> tuple[CommunicationService, CommunicationRepository, TrackingCalendar]:
    selected = adapter or TrackingCalendar()
    repository = CommunicationRepository(session, _cipher())
    return (
        CommunicationService(
            repository,
            calendar_adapters={PROVIDER: selected},
            provider_configs={
                PROVIDER: ProviderConnectionConfig(
                    provider=PROVIDER,
                    credential_reference=epoch,
                    account_hint=label,
                    granted_scopes=[WRITE_SCOPE] if scopes is None else scopes,
                    write_enabled=write,
                )
            },
            provider_account_identities={PROVIDER: identity} if identity is not None else {},
        ),
        repository,
        selected,
    )


def _fields() -> CalendarCreateFields:
    start = datetime(2026, 10, 2, 15, tzinfo=UTC)
    return CalendarCreateFields(
        title="Synthetic reviewed interview",
        start_at=start,
        end_at=start + timedelta(hours=1),
        time_zone="UTC",
        attendees=[],
        attendee_notification_policy="NONE",
        location="Synthetic test room",
    )


def _plan(service: CommunicationService) -> CalendarMutationPlan:
    return service.plan_calendar_mutation(
        CalendarMutationCreate(provider=PROVIDER, event=_fields())
    )


def _confirmation(
    plan: CalendarMutationPlan, key: str = "calendar-attempt-1"
) -> MutationConfirmation:
    return MutationConfirmation(
        fingerprint=plan.fingerprint,
        idempotency_key=key,
        confirmed_by="synthetic reviewer",
    )


def _no_attempts(session: Session, adapter: TrackingCalendar) -> None:
    assert adapter.calls == 0
    assert session.scalars(select(CalendarMutationClaimRow)).all() == []
    assert session.scalars(select(CommunicationMutationAuditRow)).all() == []


@pytest.mark.parametrize(
    "frozen_field",
    ["account_label", "calendar_target", "id_assignment", "provider_dedupe_policy"],
)
def test_plan_is_encrypted_account_bound_and_provider_native_deduplicated(
    session: Session,
    frozen_field: str,
) -> None:
    service, repository, adapter = _service(session)
    plan = _plan(service)
    assert plan == repository.get_calendar_plan(plan.id)
    assert plan.kind is MutationKind.CREATE_CALENDAR_EVENT
    assert plan.policy_version == "calendar-attempt-v1"
    assert plan.wire_contract_version == "calendar-create-wire-v1"
    assert isinstance(plan.event, CalendarCreateFields)
    assert plan.event.attendee_notification_policy == "NONE"
    assert plan.event.reminder_policy == "NONE"
    assert plan.event.visibility_policy == "PRIVATE"
    assert plan.event.availability_policy == "BUSY"
    assert plan.calendar_target == "PRIMARY"
    assert plan.id_assignment == "PROVIDER_NATIVE_DEDUPLICATED"
    assert plan.provider_dedupe_policy == "NATIVE_ATTEMPT_KEY_V1"
    assert plan.account_key is not None and len(plan.account_key) == 64
    assert plan.account_label == "candidate@example.test"
    assert plan.provider_binding_fingerprint is not None
    assert "provider_binding_fingerprint" not in plan.model_dump()
    assert "provider_event_id" not in plan.event.model_dump()
    with pytest.raises(ValidationError):
        setattr(plan, frozen_field, "different@example.test")
    row = session.get(CalendarMutationPlanRow, plan.id)
    assert row is not None
    assert plan.event.title not in row.encrypted_payload
    assert plan.account_label not in row.encrypted_payload
    assert "synthetic-calendar-account" not in row.encrypted_payload
    _no_attempts(session, adapter)


@pytest.mark.parametrize(
    "field", ["provider_event_id", "account_key", "calendar_id", "recurrence", "isAllDay"]
)
def test_create_fields_reject_unreviewed_or_ignored_authority_inputs(field: str) -> None:
    with pytest.raises(ValidationError):
        CalendarCreateFields.model_validate({**_fields().model_dump(), field: "not-honored"})


@pytest.mark.parametrize(
    "field",
    [
        "account_key",
        "account_label",
        "provider_binding_fingerprint",
        "calendar_target",
        "id_assignment",
        "provider_dedupe_policy",
        "wire_contract_version",
    ],
)
def test_plan_requests_cannot_supply_server_account_or_connection_authority(field: str) -> None:
    with pytest.raises(ValidationError):
        CalendarMutationCreate.model_validate(
            {"provider": PROVIDER, "event": _fields().model_dump(), field: "not-authoritative"}
        )


@pytest.mark.parametrize("failure", ["identity", "epoch", "label", "permission", "scope"])
def test_unverified_calendar_connections_cannot_prepare_or_reserve(
    session: Session, failure: str
) -> None:
    service, _, adapter = _service(
        session,
        identity=None if failure == "identity" else "synthetic-calendar-account",
        epoch=None if failure == "epoch" else "synthetic-calendar-epoch",
        label="candidate@example.test,other@example.test"
        if failure == "label"
        else "candidate@example.test",
        write=failure != "permission",
        scopes=[] if failure == "scope" else None,
    )
    with pytest.raises(ValueError, match="Verified calendar"):
        _plan(service)
    _no_attempts(session, adapter)


def test_dangling_workflow_id_cannot_create_a_plan(session: Session) -> None:
    service, _, adapter = _service(session)
    with pytest.raises(ValueError, match="existing application"):
        service.plan_calendar_mutation(
            CalendarMutationCreate(
                provider=PROVIDER,
                workflow_id="missing-workflow",
                event=_fields(),
            )
        )
    assert session.scalars(select(CalendarMutationPlanRow)).all() == []
    _no_attempts(session, adapter)


@pytest.mark.parametrize("change", ["identity", "epoch", "label", "scope", "permission"])
def test_reviewed_plan_never_rebinds_on_account_or_connection_change(
    session: Session, change: str
) -> None:
    original, _, adapter = _service(session)
    plan = _plan(original)
    changed, repository, _ = _service(
        session,
        adapter=adapter,
        identity="other-account" if change == "identity" else "synthetic-calendar-account",
        epoch="new-epoch-same-account" if change == "epoch" else "synthetic-calendar-epoch",
        label="renamed@example.test" if change == "label" else "candidate@example.test",
        write=change != "permission",
        scopes=[] if change == "scope" else None,
    )
    with pytest.raises(ValueError):
        changed.execute_calendar_mutation(plan.id, _confirmation(plan))
    assert repository.get_calendar_plan(plan.id) == plan
    _no_attempts(session, adapter)


def test_new_service_with_same_identity_and_epoch_keeps_review_valid(session: Session) -> None:
    original, _, adapter = _service(session)
    plan = _plan(original)
    refreshed, _, _ = _service(session, adapter=adapter)
    audit = refreshed.execute_calendar_mutation(plan.id, _confirmation(plan))
    assert audit.status is MutationStatus.CONFIRMED
    assert adapter.calls == 1


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "account_key",
        "account_label",
        "provider_binding_fingerprint",
        "id_assignment",
        "policy_version",
        "wire_contract_version",
        "calendar_target",
        "provider_dedupe_policy",
    ],
)
def test_authenticated_plan_drift_fails_before_claim_without_fingerprint_rewrite(
    session: Session, field: str
) -> None:
    service, _, adapter = _service(session)
    plan = _plan(service)
    row = session.get(CalendarMutationPlanRow, plan.id)
    assert row is not None
    payload = _cipher().decrypt_json(
        row.encrypted_payload, context=f"calendar-plan:{plan.id}:payload"
    )
    if field == "title":
        event = cast(dict[str, object], payload["event"])
        event["title"] = "Different reviewed content"
    else:
        payload[field] = (
            "f" * 64 if field.endswith("key") or field.endswith("fingerprint") else None
        )
    row.encrypted_payload = _cipher().encrypt_json(
        payload, context=f"calendar-plan:{plan.id}:payload"
    )
    session.commit()
    with pytest.raises(ValueError):
        service.execute_calendar_mutation(plan.id, _confirmation(plan))
    _no_attempts(session, adapter)


@pytest.mark.parametrize(
    "kind", [MutationKind.CREATE_CALENDAR_EVENT, MutationKind.UPDATE_CALENDAR_EVENT]
)
def test_legacy_plans_remain_readable_but_never_gain_execution_authority(
    session: Session, kind: MutationKind
) -> None:
    service, repository, adapter = _service(session)
    snapshot = CalendarEventSnapshot(
        provider_event_id="legacy-event-id",
        **_fields().model_dump(
            exclude={
                "attendee_notification_policy",
                "reminder_policy",
                "visibility_policy",
                "availability_policy",
            }
        ),
    )
    legacy = CalendarMutationPlan(
        id=str(uuid4()),
        provider=PROVIDER,
        kind=kind,
        event=snapshot,
        prior_event=snapshot if kind is MutationKind.UPDATE_CALENDAR_EVENT else None,
        fingerprint="a" * 64,
        created_at=datetime.now(UTC),
    )
    repository.save_calendar_plan(legacy)
    assert service.get_calendar_plan(legacy.id) == legacy
    with pytest.raises(ValueError, match=r"legacy|updates"):
        service.execute_calendar_mutation(legacy.id, _confirmation(legacy))
    _no_attempts(session, adapter)


def test_updates_are_refused_before_account_or_claim_checks_even_with_modern_binding(
    session: Session,
) -> None:
    service, repository, adapter = _service(session)
    plan = _plan(service)
    changed = plan.model_copy(
        update={"id": str(uuid4()), "kind": MutationKind.UPDATE_CALENDAR_EVENT}
    )
    changed = changed.model_copy(
        update={"fingerprint": service._calendar_plan_fingerprint(changed)}
    )
    repository.save_calendar_plan(changed)
    with pytest.raises(ValueError, match="updates require trusted source"):
        service.execute_calendar_mutation(changed.id, _confirmation(changed))
    with pytest.raises(ValueError, match="updates require trusted source"):
        service.plan_calendar_mutation(
            CalendarMutationCreate(
                provider=PROVIDER,
                event=_fields(),
                prior_event=CalendarEventSnapshot(
                    provider_event_id="old",
                    **_fields().model_dump(
                        exclude={
                            "attendee_notification_policy",
                            "reminder_policy",
                            "visibility_policy",
                            "availability_policy",
                        }
                    ),
                ),
            )
        )
    _no_attempts(session, adapter)


def test_unsupported_conference_link_never_creates_a_plan_or_attempt(session: Session) -> None:
    service, _, adapter = _service(session)
    fields = _fields().model_copy(
        update={"conferencing_url": "https://meeting.example.test/private"}
    )
    with pytest.raises(ValueError, match="unsupported"):
        service.plan_calendar_mutation(CalendarMutationCreate(provider=PROVIDER, event=fields))
    assert session.scalars(select(CalendarMutationPlanRow)).all() == []
    _no_attempts(session, adapter)


def test_attendees_are_rejected_before_plan_or_attempt(session: Session) -> None:
    service, _, adapter = _service(session)
    fields = _fields().model_copy(update={"attendees": ["person@example.test"]})
    with pytest.raises(ValueError, match="invalid or unsupported"):
        service.plan_calendar_mutation(CalendarMutationCreate(provider=PROVIDER, event=fields))
    assert session.scalars(select(CalendarMutationPlanRow)).all() == []
    _no_attempts(session, adapter)


def test_same_attempt_replays_after_disconnect_but_a_new_key_never_reexecutes(
    session: Session,
) -> None:
    service, _, adapter = _service(session)
    plan = _plan(service)
    confirmation = _confirmation(plan)
    first = service.execute_calendar_mutation(plan.id, confirmation)
    disconnected, _, _ = _service(session, adapter=adapter, epoch=None, identity=None)
    assert disconnected.execute_calendar_mutation(plan.id, confirmation) == first
    with pytest.raises(ValueError, match="different attempt"):
        disconnected.execute_calendar_mutation(plan.id, _confirmation(plan, "calendar-other-key"))
    assert adapter.calls == 1
    assert len(session.scalars(select(CalendarMutationClaimRow)).all()) == 1
    assert len(session.scalars(select(CommunicationMutationAuditRow)).all()) == 1


@pytest.mark.parametrize(
    "outcome", ["rejection", "generic", "uncertain", "unexpected", "invalid-result"]
)
def test_all_provider_outcomes_keep_the_plan_consumed_without_retry(
    session: Session, outcome: str
) -> None:
    service, _, adapter = _service(session)
    plan = _plan(service)
    if outcome == "rejection":
        adapter.error = ProviderCalendarNotAppliedError(
            "private provider response must not be returned"
        )
    elif outcome == "generic":
        adapter.error = ProviderMutationError("private provider response must not be returned")
    elif outcome == "uncertain":
        adapter.error = ProviderCalendarUncertainError()
    elif outcome == "unexpected":
        adapter.error = RuntimeError("private provider response must not be returned")
    else:
        adapter.invalid_result = {"private": "not an event ID"}
    audit = service.execute_calendar_mutation(plan.id, _confirmation(plan))
    assert audit.status is (
        MutationStatus.FAILED if outcome == "rejection" else MutationStatus.UNCERTAIN
    )
    assert "private" not in audit.model_dump_json()
    assert audit.provider_resource_id is None
    assert service.execute_calendar_mutation(plan.id, _confirmation(plan)) == audit
    with pytest.raises(ValueError, match="different attempt"):
        service.execute_calendar_mutation(plan.id, _confirmation(plan, "new-key-after-error"))
    assert adapter.calls == 1


def test_crash_reservation_replay_does_not_dispatch_or_release_claim(session: Session) -> None:
    service, repository, adapter = _service(session)
    plan = _plan(service)
    confirmation = _confirmation(plan)
    reserved, won = repository.claim_calendar_mutation(
        service._new_audit(
            kind=plan.kind, provider=plan.provider, resource_id=plan.id, command=confirmation
        )
    )
    assert won
    restarted, _, _ = _service(session, adapter=adapter)
    assert restarted.execute_calendar_mutation(plan.id, confirmation) == reserved
    assert reserved.status is MutationStatus.PLANNED
    assert adapter.calls == 0
    with pytest.raises(ValueError):
        restarted.execute_calendar_mutation(plan.id, _confirmation(plan, "new-key-after-crash"))


def test_lost_terminal_audit_retains_pre_dispatch_reservation(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository, adapter = _service(session)
    plan = _plan(service)

    def fail(audit: MutationAudit) -> MutationAudit:
        raise RuntimeError("synthetic database write failure")

    monkeypatch.setattr(repository, "finish_calendar_mutation", fail)
    with pytest.raises(RuntimeError, match="synthetic database"):
        service.execute_calendar_mutation(plan.id, _confirmation(plan))
    restarted, _, _ = _service(session, adapter=adapter)
    replay = restarted.execute_calendar_mutation(plan.id, _confirmation(plan))
    assert replay.status is MutationStatus.PLANNED
    assert adapter.calls == 1
    assert session.get(CalendarMutationClaimRow, plan.id) is not None
    with pytest.raises(ValueError):
        restarted.execute_calendar_mutation(
            plan.id, _confirmation(plan, "different-key-after-loss")
        )


def test_api_create_read_execute_and_conflicts_are_explicit_and_redacted(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, adapter = _service(session)
    monkeypatch.setenv("JAP_API_TOKEN", "synthetic-calendar-api-token")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_communication_service] = lambda: service
    headers = {"X-Job-Apply-Pro-Token": "synthetic-calendar-api-token"}
    client = TestClient(app)
    try:
        invalid = client.post(
            "/api/v1/communications/calendar/plans",
            headers=headers,
            json={
                "provider": PROVIDER.value,
                "event": {**_fields().model_dump(mode="json"), "provider_event_id": "caller-id"},
            },
        )
        assert invalid.status_code == 422
        created = client.post(
            "/api/v1/communications/calendar/plans",
            headers=headers,
            json={"provider": PROVIDER.value, "event": _fields().model_dump(mode="json")},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert "provider_binding_fingerprint" not in body
        assert "provider_event_id" not in body["event"]
        assert body["id_assignment"] == "PROVIDER_NATIVE_DEDUPLICATED"
        assert body["wire_contract_version"] == "calendar-create-wire-v1"
        assert body["provider_dedupe_policy"] == "NATIVE_ATTEMPT_KEY_V1"
        path = f"/api/v1/communications/calendar/plans/{body['id']}"
        assert client.get(path, headers=headers).json() == body
        confirmation = {
            "fingerprint": body["fingerprint"],
            "idempotency_key": "api-calendar-attempt",
            "confirmed_by": "synthetic reviewer",
        }
        first = client.post(f"{path}/execute", headers=headers, json=confirmation)
        assert first.status_code == 200
        assert first.json()["status"] == "CONFIRMED"
        assert (
            client.post(f"{path}/execute", headers=headers, json=confirmation).json()
            == first.json()
        )
        conflict = client.post(
            f"{path}/execute",
            headers=headers,
            json={**confirmation, "idempotency_key": "different-api-key"},
        )
        assert conflict.status_code == 409
        assert adapter.calls == 1
    finally:
        client.close()
        app.dependency_overrides.clear()
        get_settings.cache_clear()
