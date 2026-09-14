from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from job_apply_pro.config import get_settings


def _configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> tuple[str, Config]:
    url = f"sqlite:///{(tmp_path / name).as_posix()}"
    monkeypatch.setenv("JAP_DATABASE_URL", url)
    monkeypatch.setenv("JAP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    return url, Config("backend/alembic.ini")


def test_calendar_claim_migration_preserves_valid_history_and_seeds_oldest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, config = _configuration(tmp_path, monkeypatch, "legacy-calendar.db")
    engine = create_engine(url)
    try:
        command.upgrade(config, "20260913_0027")
        with engine.begin() as connection:
            plans = (
                ("old-plan", "CREATE_CALENDAR_EVENT", "a" * 64),
                ("failed-plan", "UPDATE_CALENDAR_EVENT", "b" * 64),
                ("untouched-plan", "CREATE_CALENDAR_EVENT", "c" * 64),
                ("mail-only-plan", "CREATE_CALENDAR_EVENT", "d" * 64),
            )
            for plan_id, kind, fingerprint in plans:
                connection.execute(
                    text(
                        "INSERT INTO calendar_mutation_plans "
                        "(id,provider,kind,fingerprint,encrypted_payload,created_at) VALUES "
                        "(:id,'GOOGLE_CALENDAR',:kind,:fingerprint,:payload,'2026-09-13')"
                    ),
                    {
                        "id": plan_id,
                        "kind": kind,
                        "fingerprint": fingerprint,
                        "payload": f"unchanged-{plan_id}-ciphertext",
                    },
                )
            audits = (
                (
                    "later",
                    "old-plan",
                    "CREATE_CALENDAR_EVENT",
                    "a" * 64,
                    "CONFIRMED",
                    "2026-09-14",
                    "legacy-later-id",
                    None,
                ),
                (
                    "b-oldest",
                    "old-plan",
                    "CREATE_CALENDAR_EVENT",
                    "a" * 64,
                    "CONFIRMED",
                    "2026-09-13",
                    "legacy-oldest-id",
                    None,
                ),
                (
                    "a-oldest",
                    "old-plan",
                    "CREATE_CALENDAR_EVENT",
                    "a" * 64,
                    "UNCERTAIN",
                    "2026-09-13",
                    None,
                    "LegacyUncertain",
                ),
                (
                    "mail-earliest",
                    "old-plan",
                    "SEND_MESSAGE",
                    "z" * 64,
                    "CONFIRMED",
                    "2026-09-12",
                    "mail-id",
                    None,
                ),
                (
                    "failed",
                    "failed-plan",
                    "UPDATE_CALENDAR_EVENT",
                    "b" * 64,
                    "FAILED",
                    "2026-09-13",
                    None,
                    "LegacyRejected",
                ),
                (
                    "planned-later",
                    "failed-plan",
                    "UPDATE_CALENDAR_EVENT",
                    "b" * 64,
                    "PLANNED",
                    "2026-09-14",
                    None,
                    None,
                ),
                (
                    "mail-only",
                    "mail-only-plan",
                    "SEND_MESSAGE",
                    "z" * 64,
                    "PLANNED",
                    "2026-09-13",
                    None,
                    None,
                ),
            )
            for (
                audit_id,
                plan_id,
                kind,
                fingerprint,
                status,
                occurred_at,
                provider_id,
                error_code,
            ) in audits:
                connection.execute(
                    text(
                        "INSERT INTO communication_mutation_audits "
                        "(id,kind,provider,resource_id,idempotency_key,fingerprint,status,"
                        "confirmed_by,provider_resource_id,error_code,occurred_at) VALUES "
                        "(:id,:kind,'GOOGLE_CALENDAR',:plan,:key,:fingerprint,:status,"
                        "'legacy-review',:provider_id,:error_code,:occurred)"
                    ),
                    {
                        "id": audit_id,
                        "kind": kind,
                        "plan": plan_id,
                        "key": f"legacy-key-{audit_id}",
                        "fingerprint": fingerprint,
                        "status": status,
                        "occurred": occurred_at,
                        "provider_id": provider_id,
                        "error_code": error_code,
                    },
                )
            before = {
                table: connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
                for table in ("calendar_mutation_plans", "communication_mutation_audits")
            }
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        inspector = inspect(engine)
        assert inspector.get_pk_constraint("calendar_mutation_claims")["constrained_columns"] == [
            "plan_id"
        ]
        assert any(
            item["column_names"] == ["audit_id"]
            for item in inspector.get_unique_constraints("calendar_mutation_claims")
        )
        assert {
            tuple(item["constrained_columns"])
            for item in inspector.get_foreign_keys("calendar_mutation_claims")
        } == {("plan_id",), ("audit_id",)}
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT plan_id,audit_id FROM calendar_mutation_claims ORDER BY plan_id")
            ).tuples().all() == [("failed-plan", "failed"), ("old-plan", "a-oldest")]
            for table, previous in before.items():
                assert (
                    connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all() == previous
                )
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        with pytest.raises(RuntimeError, match="history prevents downgrade"):
            command.downgrade(config, "20260913_0027")
        assert "calendar_mutation_claims" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "mismatch",
    [
        "orphan",
        "provider",
        "noncalendar",
        "kind",
        "fingerprint",
        "status",
        "shape",
        "provider_id_control",
        "error_control",
    ],
)
def test_calendar_claim_migration_aborts_on_malformed_attempt_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    url, config = _configuration(tmp_path, monkeypatch, f"invalid-{mismatch}.db")
    engine = create_engine(url)
    try:
        command.upgrade(config, "20260913_0027")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO calendar_mutation_plans "
                    "(id,provider,kind,fingerprint,encrypted_payload,created_at) VALUES "
                    "('plan',:plan_provider,'CREATE_CALENDAR_EVENT',:fingerprint,'cipher','2026-09-13')"
                ),
                {
                    "plan_provider": "GMAIL" if mismatch == "noncalendar" else "GOOGLE_CALENDAR",
                    "fingerprint": "a" * 64,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO communication_mutation_audits "
                    "(id,kind,provider,resource_id,idempotency_key,fingerprint,status,"
                    "confirmed_by,provider_resource_id,error_code,occurred_at) VALUES "
                    "('audit',:kind,:provider,:resource,'key',:fingerprint,:status,'actor',"
                    ":provider_id,:error_code,'2026-09-13')"
                ),
                {
                    "kind": "UPDATE_CALENDAR_EVENT"
                    if mismatch == "kind"
                    else "CREATE_CALENDAR_EVENT",
                    "provider": (
                        "OUTLOOK_CALENDAR"
                        if mismatch == "provider"
                        else "GMAIL"
                        if mismatch == "noncalendar"
                        else "GOOGLE_CALENDAR"
                    ),
                    "resource": "missing" if mismatch == "orphan" else "plan",
                    "fingerprint": "b" * 64 if mismatch == "fingerprint" else "a" * 64,
                    "status": (
                        "ACCEPTED"
                        if mismatch == "status"
                        else "CONFIRMED"
                        if mismatch == "provider_id_control"
                        else "FAILED"
                        if mismatch == "error_control"
                        else "PLANNED"
                    ),
                    "provider_id": (
                        "invalid-for-planned"
                        if mismatch == "shape"
                        else "bad\nprovider-id"
                        if mismatch == "provider_id_control"
                        else None
                    ),
                    "error_code": "bad\nerror" if mismatch == "error_control" else None,
                },
            )
        with pytest.raises(RuntimeError, match="history is inconsistent"):
            command.upgrade(config, "head")
        assert "calendar_mutation_claims" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260913_0027"
            )
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_calendar_claim_migration_refuses_downgrade_with_plan_only_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, config = _configuration(tmp_path, monkeypatch, "plan-only-calendar.db")
    engine = create_engine(url)
    try:
        command.upgrade(config, "20260913_0027")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO calendar_mutation_plans "
                    "(id,provider,kind,fingerprint,encrypted_payload,created_at) VALUES "
                    "('plan','GOOGLE_CALENDAR','CREATE_CALENDAR_EVENT',:fingerprint,'cipher',"
                    "'2026-09-13')"
                ),
                {"fingerprint": "a" * 64},
            )
        command.upgrade(config, "head")
        with pytest.raises(RuntimeError, match="history prevents downgrade"):
            command.downgrade(config, "20260913_0027")
        assert "calendar_mutation_claims" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_calendar_claim_migration_downgrades_only_when_no_attempt_history_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, config = _configuration(tmp_path, monkeypatch, "empty-calendar.db")
    engine = create_engine(url)
    try:
        command.upgrade(config, "head")
        command.downgrade(config, "20260913_0027")
        assert "calendar_mutation_claims" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        get_settings.cache_clear()
