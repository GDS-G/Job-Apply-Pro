"""Bounded corruption, schema and authority-only forward-restore inspection tests."""

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

from job_apply_pro.config import get_settings
from job_apply_pro.domain.ai import AICacheRecord, DataClassification
from job_apply_pro.domain.communications import (
    CalendarEventSnapshot,
    CalendarMutationPlan,
    IntegrationProvider,
    MutationKind,
)
from job_apply_pro.integrations.communications import FixtureCalendarProvider
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services import restore_history as guard
from job_apply_pro.storage import restore_history_repository as inspection
from job_apply_pro.storage.ai_repository import AIGatewayRepository
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.restore_gate_repository import RestoreGateRepository
from job_apply_pro.storage.restore_history_policy import (
    COMPATIBLE_EXTRA_INDEXES,
    INDEXES,
    MIGRATION_DEFAULTS,
    MODERN_REVISION,
    TABLES,
    UNIQUES,
    sqlite_declaration,
)
from test_forward_restore_history import (
    _NOW,
    _PROVIDER,
    _calendar_plan,
    _calendar_service,
    _close_media,
    _confirmation,
    _HistoryRestore,
    _invocation,
    _media_intent,
)
from test_forward_restore_history import history as history


def _sql(path: Path, statement: str, parameters: tuple[object, ...] = ()) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(statement, parameters)


def _snapshot_bytes(*paths: Path) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _inspect_refused(path: Path, *, message: str = inspection.UNAVAILABLE) -> None:
    before = _snapshot_bytes(path)
    with pytest.raises(inspection.RestoreHistoryError) as error:
        inspection.inspect_history(path)
    assert str(error.value) == message
    assert _snapshot_bytes(path) == before
    assert str(path) not in str(error.value)


def _service(history: _HistoryRestore, staged: Path | None = None) -> None:
    guard.require_preserved_history(
        history.database,
        staged,
        cipher=history.cipher,
        documents=history.documents,
        staged_documents=None,
    )


def _service_refused(
    history: _HistoryRestore,
    staged: Path | None = None,
    *,
    message: str = inspection.UNAVAILABLE,
) -> None:
    paths = (history.database,) if staged is None else (history.database, staged)
    before = _snapshot_bytes(*paths)
    with pytest.raises(inspection.RestoreHistoryError, match=message) as error:
        _service(history, staged)
    assert _snapshot_bytes(*paths) == before
    assert str(history.root) not in str(error.value)
    assert "synthetic-cache" not in str(error.value)
    assert not (RestoreGateRepository(history.root).control / "operations").exists()


def _row(table: str, *, identity: str = "a") -> dict[str, object]:
    """Scalar-valid rows for direct inspection; no relational-validity claim."""
    values: dict[str, object] = {}
    for column in TABLES[table].columns:
        if column.nullable:
            value: object = None
        elif column.kind == "json":
            value = "{}"
        elif column.kind in {"boolean", "integer"}:
            value = 1
        elif column.kind == "float":
            value = 0.5
        elif column.kind == "datetime":
            value = _NOW.isoformat()
        elif column.kind == "date":
            value = _NOW.date().isoformat()
        else:
            value = identity * min(column.limit, 8)
        values[column.name] = value
    return values


def _insert(path: Path, table: str, row: dict[str, object]) -> None:
    columns = ", ".join(f'"{column}"' for column in row)
    parameters = ", ".join("?" for _ in row)
    _sql(path, f'INSERT INTO "{table}" ({columns}) VALUES ({parameters})', tuple(row.values()))


def _remove_constraints(path: Path, table: str) -> None:
    # Model a damaged snapshot whose expected columns survived but constraints did not.
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(f'CREATE TABLE synthetic_replacement AS SELECT * FROM "{table}"')
        connection.execute(f'DROP TABLE "{table}"')
        connection.execute(f'ALTER TABLE synthetic_replacement RENAME TO "{table}"')


@pytest.mark.parametrize("table", sorted(TABLES))
def test_explicit_descriptor_matches_model_columns_keys_references_and_uniques(table: str) -> None:
    assert len(TABLES) == 47
    spec = TABLES[table]
    model = Base.metadata.tables[table]
    assert {column.name for column in spec.columns} == set(model.columns.keys())
    expected_types = {
        "text": String,
        "json": JSON,
        "integer": Integer,
        "boolean": Boolean,
        "float": Float,
        "datetime": DateTime,
        "date": Date,
    }
    for column in spec.columns:
        actual = model.columns[column.name]
        assert column.nullable == actual.nullable
        assert isinstance(actual.type, expected_types[column.kind])
        assert sqlite_declaration(column) == actual.type.compile(dialect=sqlite_dialect()).upper()
        if column.kind == "text":
            assert isinstance(actual.type, String)
            if actual.type.length is not None:
                assert column.limit == actual.type.length
    assert spec.key == tuple(column.name for column in model.primary_key.columns)
    assert set(spec.references) == {
        (foreign.parent.name, foreign.column.table.name, foreign.column.name)
        for foreign in model.foreign_keys
    }
    unique_keys = {
        tuple(column.name for column in constraint.columns)
        for constraint in model.constraints
        if isinstance(constraint, UniqueConstraint)
    } | {tuple(column.name for column in index.columns) for index in model.indexes if index.unique}
    assert set(UNIQUES.get(table, ())) == unique_keys
    expected_indexes = {
        index.name: tuple(column.name for column in index.columns) for index in model.indexes
    }
    assert {index.name: index.columns for index in INDEXES.get(table, ())} == expected_indexes
    assert not (
        expected_indexes.keys() & {index.name for index in COMPATIBLE_EXTRA_INDEXES.get(table, ())}
    )


def test_reviewed_migration_defaults_only_name_protected_columns() -> None:
    for (table, column), defaults in MIGRATION_DEFAULTS.items():
        assert column in {item.name for item in TABLES[table].columns}
        assert None in defaults


@pytest.mark.parametrize(
    "statement",
    [
        "DROP TABLE alembic_version",
        "DELETE FROM alembic_version",
        "INSERT INTO alembic_version VALUES ('20260913_0028')",
        "UPDATE alembic_version SET version_num='20260913_9999'",
        "UPDATE alembic_version SET version_num='20260814_0023'",
        "DROP TABLE oauth_credentials",
        "ALTER TABLE oauth_credentials DROP COLUMN encrypted_token_set",
        "ALTER TABLE oauth_credentials ADD COLUMN unreviewed_authority TEXT",
        "ALTER TABLE oauth_credentials RENAME TO OAUTH_CREDENTIALS_UNREVIEWED",
        "CREATE VIEW synthetic_view AS SELECT * FROM oauth_credentials",
        "CREATE TRIGGER synthetic_trigger AFTER INSERT ON oauth_credentials BEGIN SELECT 1; END",
    ],
)
def test_missing_unknown_or_executable_schema_is_not_empty_history(
    history: _HistoryRestore, statement: str
) -> None:
    _sql(history.database, statement)
    _inspect_refused(history.database)


def test_view_cannot_impersonate_a_protected_table(history: _HistoryRestore) -> None:
    _sql(history.database, "DROP TABLE ai_cache")
    _sql(history.database, "CREATE VIEW ai_cache AS SELECT 1 AS key")
    _inspect_refused(history.database)


def test_empty_table_without_declared_constraints_is_refused(history: _HistoryRestore) -> None:
    _remove_constraints(history.database, "mail_send_claims")
    _inspect_refused(history.database)


@pytest.mark.parametrize(
    "statement",
    [
        "DROP INDEX ix_jobs_employer",
        "CREATE INDEX synthetic_unreviewed_index ON jobs(title)",
        "DROP INDEX ix_oauth_credentials_provider",
        "ALTER TABLE jobs ADD COLUMN synthetic_generated TEXT GENERATED ALWAYS AS (title) VIRTUAL",
    ],
)
def test_unreviewed_physical_index_or_generated_column_is_refused(
    history: _HistoryRestore, statement: str
) -> None:
    _sql(history.database, statement)
    _inspect_refused(history.database)


def test_index_direction_and_collation_are_physical_policy(history: _HistoryRestore) -> None:
    _sql(history.database, "DROP INDEX ix_jobs_employer")
    _sql(
        history.database,
        "CREATE INDEX ix_jobs_employer ON jobs(employer COLLATE NOCASE DESC)",
    )
    _inspect_refused(history.database)


def test_foreign_key_actions_are_physical_policy(history: _HistoryRestore) -> None:
    with closing(sqlite3.connect(history.database)) as connection, connection:
        connection.execute("DROP TABLE mail_send_claims")
        connection.execute(
            "CREATE TABLE mail_send_claims ("
            "draft_id VARCHAR(36) NOT NULL PRIMARY KEY, "
            "audit_id VARCHAR(36) NOT NULL UNIQUE, "
            "FOREIGN KEY(draft_id) REFERENCES outbound_drafts(id) ON DELETE CASCADE, "
            "FOREIGN KEY(audit_id) REFERENCES communication_mutation_audits(id))"
        )
    _inspect_refused(history.database)


def test_unreviewed_column_default_is_refused_on_an_empty_table(
    history: _HistoryRestore,
) -> None:
    with closing(sqlite3.connect(history.database)) as connection, connection:
        connection.execute("DROP TABLE ai_cache")
        connection.execute(
            "CREATE TABLE ai_cache ("
            '"key" VARCHAR(64) NOT NULL PRIMARY KEY, '
            "profile_id VARCHAR(36), "
            "classification VARCHAR(40) NOT NULL DEFAULT 'ROUTINE', "
            "encrypted_response TEXT NOT NULL, "
            "expires_at DATETIME NOT NULL, "
            "created_at DATETIME NOT NULL)"
        )
        connection.execute("CREATE INDEX ix_ai_cache_expires_at ON ai_cache(expires_at)")
        connection.execute("CREATE INDEX ix_ai_cache_profile_id ON ai_cache(profile_id)")
    _inspect_refused(history.database)


@pytest.mark.parametrize("contents", [None, b"synthetic-not-a-sqlite-database"])
def test_missing_or_corrupt_database_is_not_created_or_replaced(
    tmp_path: Path, contents: bytes | None
) -> None:
    path = tmp_path / "unavailable.db"
    if contents is not None:
        path.write_bytes(contents)
    _inspect_refused(path)


@pytest.mark.parametrize("identity", ["duplicate", "empty", "null"])
def test_lost_primary_key_constraint_does_not_hide_invalid_identity(
    history: _HistoryRestore, identity: str
) -> None:
    table = "model_invocations"
    _remove_constraints(history.database, table)
    first = _row(table)
    _insert(history.database, table, first)
    second = dict(first)
    second["id"] = first["id"] if identity == "duplicate" else ("" if identity == "empty" else None)
    _insert(history.database, table, second)
    _inspect_refused(history.database)


_UNIQUE_CASES = [(table, unique) for table, keys in UNIQUES.items() for unique in keys]


@pytest.mark.parametrize(
    ("table", "unique"),
    _UNIQUE_CASES,
    ids=[f"{table}:{','.join(key)}" for table, key in _UNIQUE_CASES],
)
def test_lost_unique_constraint_does_not_hide_duplicate_replay_or_source_identity(
    history: _HistoryRestore, table: str, unique: tuple[str, ...]
) -> None:
    _remove_constraints(history.database, table)
    first = _row(table)
    for field in unique:
        if first[field] is None:
            first[field] = "synthetic-unique-value"
    second = dict(first)
    key_column = next(column for column in TABLES[table].key if column not in unique)
    second[key_column] = "synthetic-second-id"
    _insert(history.database, table, first)
    _insert(history.database, table, second)
    _inspect_refused(history.database)


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("model_invocations", "attempts", "synthetic-noninteger"),
        ("model_invocations", "provider", sqlite3.Binary(b"not-text")),
        ("model_invocations", "provider", "p" * 81),
        ("model_invocations", "created_at", "synthetic-invalid-date"),
        ("browser_sessions", "headless", 2),
        ("candidate_claims", "start_date", "2026-99-99"),
        ("fit_scores", "score", float("inf")),
        ("fit_scores", "score", "not-numeric"),
    ],
)
def test_wrong_scalar_types_and_bounds_are_refused(
    history: _HistoryRestore, table: str, column: str, value: object
) -> None:
    row = _row(table)
    row[column] = value
    _insert(history.database, table, row)
    _inspect_refused(history.database)


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        '{"duplicate":1,"duplicate":2}',
        "NaN",
        "Infinity",
        "-Infinity",
        "1e999",
        "[" * 34 + "0" + "]" * 34,
        "[" + ",".join("0" for _ in range(50_001)) + "]",
    ],
    ids=["invalid", "duplicate-key", "nan", "inf", "negative-inf", "overflow", "depth", "nodes"],
)
def test_unbounded_or_ambiguous_plaintext_json_is_refused(
    history: _HistoryRestore, payload: str
) -> None:
    row = _row("model_invocations")
    row["route_json"] = payload
    _insert(history.database, "model_invocations", row)
    _inspect_refused(history.database)


@pytest.mark.parametrize(
    "limit", ["MAX_ROWS", "MAX_TOTAL_ROWS", "MAX_TOTAL_BYTES", "MAX_CELL_BYTES"]
)
def test_inspection_limits_fail_closed_without_large_fixtures(
    history: _HistoryRestore, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    row = _row("model_invocations")
    if limit == "MAX_CELL_BYTES":
        row["route_json"] = '"' + "é" * 700 + '"'
        monkeypatch.setattr(inspection, limit, 1024)
    elif limit == "MAX_TOTAL_BYTES":
        monkeypatch.setattr(inspection, limit, 64)
    else:
        monkeypatch.setattr(inspection, limit, 1)
        second = _row("jobs" if limit == "MAX_TOTAL_ROWS" else "model_invocations", identity="b")
        _insert(
            history.database, "jobs" if limit == "MAX_TOTAL_ROWS" else "model_invocations", second
        )
    _insert(history.database, "model_invocations", row)
    _inspect_refused(history.database)


def test_inspection_deadline_is_enforced_without_sleeping(
    history: _HistoryRestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _insert(history.database, "model_invocations", _row("model_invocations"))
    ticks = iter([0.0])
    monkeypatch.setattr(
        inspection,
        "time",
        SimpleNamespace(monotonic=lambda: next(ticks, inspection.INSPECTION_SECONDS + 1)),
    )
    _inspect_refused(history.database)


@pytest.fixture(
    scope="module",
    params=["20260913_0025", "20260913_0026", "20260913_0027", "20260913_0028"],
)
def legacy_template(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    root = tmp_path_factory.mktemp(f"real-migration-{request.param}")
    path = root / "legacy.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("JAP_DATABASE_URL", f"sqlite:///{path.as_posix()}")
        environment.setenv("JAP_WORKSPACE_ROOT", str(root))
        get_settings.cache_clear()
        try:
            command.upgrade(config, str(request.param))
        finally:
            get_settings.cache_clear()
    return path


@pytest.fixture
def legacy_history(legacy_template: Path, tmp_path: Path) -> _HistoryRestore:
    history = _HistoryRestore(tmp_path, SensitiveDataCipher(StaticKeyProvider(b"l" * 32)))
    shutil.copyfile(legacy_template, history.database)
    history.documents.mkdir()
    return history


def test_real_modern_migration_physical_schema_is_admitted(tmp_path: Path) -> None:
    root = tmp_path / "real-modern-migration"
    root.mkdir()
    path = root / "modern.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("JAP_DATABASE_URL", f"sqlite:///{path.as_posix()}")
        environment.setenv("JAP_WORKSPACE_ROOT", str(root))
        get_settings.cache_clear()
        try:
            command.upgrade(config, MODERN_REVISION)
        finally:
            get_settings.cache_clear()
    snapshot = inspection.inspect_history(path)
    assert snapshot.revision == MODERN_REVISION
    assert not snapshot.has_history


def _seed_prepared_external_effect(
    history: _HistoryRestore, *, sequence: int = 1
) -> tuple[str, str]:
    operation_id = str(uuid4())
    attempt_id = str(uuid4())
    _insert(
        history.database,
        "external_effect_operations",
        {
            "id": operation_id,
            "claim_fingerprint": "a" * 64,
            "kind": "AI_COMPLETION",
            "subject_type": "ai_request",
            "subject_id": "b" * 64,
            "actor": "ai-gateway",
            "request_fingerprint": "c" * 64,
            "policy_version": "external-effects-v1",
            "status": "PREPARED",
            "result_reference": None,
            "result_fingerprint": None,
            "error_code": None,
            "created_at": _NOW.isoformat(),
            "updated_at": _NOW.isoformat(),
            "completed_at": None,
        },
    )
    _insert(
        history.database,
        "external_effect_attempts",
        {
            "id": attempt_id,
            "operation_id": operation_id,
            "sequence": sequence,
            "provider": "local",
            "target_code": "local.answer",
            "request_fingerprint": "d" * 64,
            "native_key_fingerprint": None,
            "status": "PREPARED",
            "result_reference": None,
            "result_fingerprint": None,
            "error_code": None,
            "input_tokens": None,
            "output_tokens": None,
            "cost_micros": None,
            "created_at": _NOW.isoformat(),
            "updated_at": _NOW.isoformat(),
            "completed_at": None,
        },
    )
    return operation_id, attempt_id


def test_prepared_external_effect_history_is_semantically_admitted(
    history: _HistoryRestore,
) -> None:
    _seed_prepared_external_effect(history)
    _service(history)


def _reviewed_reconciliation_payload(kind: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "action_kind": (
            "CLICK"
            if kind in {"BROWSER_NAVIGATION_CONFIRMED", "BROWSER_SUBMISSION_CONFIRMED"}
            else "UPLOAD"
        ),
        "control_key": "greenhouse-resume",
        "locator": {
            "strategy": "LABEL",
            "value": "Resume",
            "name": None,
            "exact": True,
        },
        "request_fingerprint": "a" * 64,
        "source_form_review_fingerprint": "b" * 64,
        "source_origin": "https://boards.greenhouse.io",
        "source_page_type": "DOCUMENT_UPLOAD",
        "source_stage": "DOCUMENTS",
    }
    if kind == "BROWSER_UPLOAD_CONFIRMED":
        payload.update(
            {
                "expected_file_bytes": 1_024,
                "expected_file_name": "candidate-resume.pdf",
                "expected_file_sha256": "c" * 64,
                "source_upload_status_fingerprint": "d" * 64,
            }
        )
    elif kind == "BROWSER_SUBMISSION_CONFIRMED":
        payload.update(
            {
                "control_key": "greenhouse-submit",
                "locator": {
                    "strategy": "ROLE",
                    "value": "button",
                    "name": "Submit application",
                    "exact": True,
                },
                "portal": "GREENHOUSE",
                "portal_adapter_version": "1.0.0",
                "postcondition": "IDENTIFIER_BACKED_CONFIRMATION",
                "source_page_type": "SUBMISSION_REVIEW",
                "source_stage": "REVIEW",
            }
        )
    return payload


@pytest.mark.parametrize(
    "kind",
    [
        "BROWSER_NAVIGATION_CONFIRMED",
        "BROWSER_UPLOAD_CONFIRMED",
        "BROWSER_SUBMISSION_CONFIRMED",
    ],
)
def test_restore_authenticates_kind_specific_reviewed_reconciliation_payload(
    kind: str,
) -> None:
    guard._authenticate_external_effect_reconciliation(
        {"kind": kind},
        _reviewed_reconciliation_payload(kind),
        "a" * 64,
    )


def _exact_url_navigation_payload() -> dict[str, object]:
    return {
        "action_kind": "NAVIGATE",
        "navigation_scope": "EXACT_URL",
        "postcondition": "URL_EQUALS",
        "request_fingerprint": "a" * 64,
        "source_origin": "https://careers.example.com",
        "source_page_type": "JOB_DETAIL",
        "source_url": "https://careers.example.com/jobs/123",
        "target_origin": "https://apply.example.com",
        "target_url": "https://apply.example.com/applications/123",
    }


def test_restore_authenticates_exact_url_navigation_reconciliation_payload() -> None:
    guard._authenticate_external_effect_reconciliation(
        {"kind": "BROWSER_NAVIGATION_CONFIRMED"},
        _exact_url_navigation_payload(),
        "a" * 64,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action_kind", "CLICK"),
        ("navigation_scope", "GENERIC_CLICK"),
        ("postcondition", "URL_CONTAINS"),
        ("source_origin", "https://other.example.com"),
        ("source_url", "https://user:secret@careers.example.com/jobs/123"),
        ("target_origin", "https://other.example.com"),
        ("target_url", "javascript:alert(1)"),
        ("source_page_type", ""),
        ("request_fingerprint", "e" * 64),
    ],
)
def test_restore_refuses_changed_exact_url_navigation_meaning(field: str, value: object) -> None:
    payload = _exact_url_navigation_payload()
    payload[field] = value
    with pytest.raises(inspection.RestoreHistoryError, match=inspection.UNAVAILABLE):
        guard._authenticate_external_effect_reconciliation(
            {"kind": "BROWSER_NAVIGATION_CONFIRMED"},
            payload,
            "a" * 64,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_file_name", "../candidate-resume.pdf"),
        ("expected_file_name", "candidate-resume.exe"),
        ("expected_file_bytes", True),
        ("source_stage", "QUESTIONNAIRE"),
        ("source_origin", "https://user:secret@boards.greenhouse.io"),
        ("expected_file_sha256", "not-a-fingerprint"),
        ("request_fingerprint", "e" * 64),
    ],
)
def test_restore_refuses_changed_reviewed_upload_meaning(field: str, value: object) -> None:
    payload = _reviewed_reconciliation_payload("BROWSER_UPLOAD_CONFIRMED")
    payload[field] = value
    with pytest.raises(inspection.RestoreHistoryError, match=inspection.UNAVAILABLE):
        guard._authenticate_external_effect_reconciliation(
            {"kind": "BROWSER_UPLOAD_CONFIRMED"},
            payload,
            "a" * 64,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action_kind", "UPLOAD"),
        ("portal", "INDEED"),
        ("portal_adapter_version", ""),
        ("postcondition", "NEXT_STAGE_OBSERVED"),
        ("source_page_type", "QUESTIONNAIRE"),
        ("source_stage", "QUESTIONNAIRE"),
        ("source_origin", "https://example.com"),
        ("request_fingerprint", "e" * 64),
    ],
)
def test_restore_refuses_changed_reviewed_submission_meaning(field: str, value: object) -> None:
    payload = _reviewed_reconciliation_payload("BROWSER_SUBMISSION_CONFIRMED")
    payload[field] = value
    with pytest.raises(inspection.RestoreHistoryError, match=inspection.UNAVAILABLE):
        guard._authenticate_external_effect_reconciliation(
            {"kind": "BROWSER_SUBMISSION_CONFIRMED"},
            payload,
            "a" * 64,
        )


@pytest.mark.parametrize(
    ("statement", "parameters"),
    [
        (
            "UPDATE external_effect_operations SET status='DISPATCHING' WHERE id=?",
            "operation",
        ),
        (
            "UPDATE external_effect_attempts SET sequence=2 WHERE id=?",
            "attempt",
        ),
    ],
)
def test_inconsistent_external_effect_state_is_refused(
    history: _HistoryRestore, statement: str, parameters: str
) -> None:
    operation_id, attempt_id = _seed_prepared_external_effect(history)
    _sql(history.database, statement, (operation_id if parameters == "operation" else attempt_id,))
    _service_refused(history)


def test_confirmed_external_effect_requires_its_local_evidence(
    history: _HistoryRestore,
) -> None:
    operation_id, attempt_id = _seed_prepared_external_effect(history)
    reference = f"model-invocation:{attempt_id}"
    for table, identity in (
        ("external_effect_operations", operation_id),
        ("external_effect_attempts", attempt_id),
    ):
        _sql(
            history.database,
            f'UPDATE "{table}" SET status="CONFIRMED", result_reference=?, '
            "result_fingerprint=?, completed_at=? WHERE id=?",
            (reference, "e" * 64, _NOW.isoformat(), identity),
        )
    _service_refused(history)


def test_real_legacy_migration_with_empty_history_and_authority_is_admitted(
    legacy_history: _HistoryRestore,
) -> None:
    before = legacy_history.database.read_bytes()
    snapshot = inspection.inspect_history(legacy_history.database)
    assert snapshot.revision in {
        "20260913_0025",
        "20260913_0026",
        "20260913_0027",
        "20260913_0028",
    }
    assert snapshot.revision != MODERN_REVISION
    assert not snapshot.has_history
    assert not snapshot.tables["job_readiness_reviews"]
    assert not snapshot.tables["calendar_mutation_claims"]
    _service(legacy_history)
    assert legacy_history.database.read_bytes() == before


_CACHES = ("ai_cache", "provider_sync_states", "provider_calendar_events")


def _seed_cache(history: _HistoryRestore, table: str, *, value: str = "first") -> tuple[str, str]:
    with history.session() as session:
        if table == "ai_cache":
            context = f"ai-cache:{'a' * 64}"
            AIGatewayRepository(session).upsert_cache(
                AICacheRecord(
                    key="a" * 64,
                    classification=DataClassification.ROUTINE,
                    encrypted_response=history.cipher.encrypt_json(
                        {"content": f"synthetic-cache-{value}"}, context=context
                    ),
                    expires_at=_NOW,
                    created_at=_NOW,
                )
            )
            return "encrypted_response", context
        repository = CommunicationRepository(session, history.cipher)
        if table == "provider_sync_states":
            repository.save_sync_state(
                _PROVIDER, SecretStr(f"synthetic-cache-{value}"), "b" * 64, None
            )
            return "encrypted_cursor", f"provider-sync:{_PROVIDER.value}:cursor"
        event = CalendarEventSnapshot(
            provider_event_id="synthetic-cache-event",
            title=f"synthetic-cache-{value}",
            start_at=_NOW,
            end_at=_NOW.replace(hour=13),
            time_zone="UTC",
        )
        repository.reconcile_calendar_events(
            _PROVIDER, "b" * 64, [event], window_start=_NOW, window_end=_NOW.replace(hour=14)
        )
        fingerprint = hashlib.sha256(
            f"{_PROVIDER.value}\0{event.provider_event_id}".encode()
        ).hexdigest()
        return "encrypted_event", f"calendar-event:{_PROVIDER.value}:{fingerprint}:payload"


@pytest.mark.parametrize("table", (*_CACHES, "model_invocations"))
def test_real_legacy_migration_with_history_or_cache_authority_is_refused(
    legacy_history: _HistoryRestore, table: str
) -> None:
    if table == "model_invocations":
        with legacy_history.session() as session:
            AIGatewayRepository(session).add_invocation(_invocation())
    else:
        _seed_cache(legacy_history, table)
    _inspect_refused(
        legacy_history.database,
        message=(
            "Legacy recorded history requires a post-upgrade complete backup; "
            "restore was not applied"
        ),
    )


def _seed_calendar_attempt(history: _HistoryRestore) -> tuple[str, str, str]:
    adapter = FixtureCalendarProvider(_PROVIDER)
    with history.session() as session:
        service = _calendar_service(session, history, adapter)
        plan = _calendar_plan(service, _PROVIDER)
        audit = service.execute_calendar_mutation(plan.id, _confirmation(plan))
    return plan.id, audit.id, plan.fingerprint


@pytest.mark.parametrize(
    ("table", "identity_column"),
    [
        ("calendar_mutation_plans", "id"),
        ("communication_mutation_audits", "id"),
        ("calendar_mutation_claims", "plan_id"),
    ],
)
def test_calendar_plan_audit_or_claim_loss_is_never_valid_history(
    history: _HistoryRestore, table: str, identity_column: str
) -> None:
    plan_id, audit_id, _fingerprint = _seed_calendar_attempt(history)
    identity = (
        plan_id if identity_column != "id" or table != "communication_mutation_audits" else audit_id
    )
    _sql(history.database, f'DELETE FROM "{table}" WHERE "{identity_column}"=?', (identity,))
    _service_refused(history)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "GMAIL"),
        ("kind", "UPDATE_CALENDAR_EVENT"),
        ("resource_id", "different-plan"),
        ("fingerprint", "b" * 64),
    ],
)
def test_calendar_claim_rejects_changed_audit_relationship(
    history: _HistoryRestore, field: str, value: str
) -> None:
    _plan_id, audit_id, _fingerprint = _seed_calendar_attempt(history)
    _sql(
        history.database,
        f'UPDATE communication_mutation_audits SET "{field}"=? WHERE id=?',
        (value, audit_id),
    )
    _service_refused(history)


def test_calendar_claim_cannot_be_fabricated_for_a_noncalendar_audit(
    history: _HistoryRestore,
) -> None:
    adapter = FixtureCalendarProvider(_PROVIDER)
    with history.session() as session:
        plan = _calendar_plan(_calendar_service(session, history, adapter), _PROVIDER)
    _sql(
        history.database,
        "INSERT INTO communication_mutation_audits "
        "(id,kind,provider,resource_id,idempotency_key,fingerprint,status,confirmed_by,"
        "occurred_at) "
        "VALUES ('fabricated-audit','SEND_MESSAGE','GOOGLE_CALENDAR',?,'fabricated-key',?,"
        "'PLANNED','synthetic-reviewer',?)",
        (plan.id, plan.fingerprint, _NOW.isoformat()),
    )
    _sql(
        history.database,
        "INSERT INTO calendar_mutation_claims (plan_id,audit_id) VALUES (?, 'fabricated-audit')",
        (plan.id,),
    )
    _service_refused(history)


def test_calendar_claim_must_reference_deterministic_oldest_attempt(
    history: _HistoryRestore,
) -> None:
    plan_id, _audit_id, fingerprint = _seed_calendar_attempt(history)
    _sql(
        history.database,
        "INSERT INTO communication_mutation_audits "
        "(id,kind,provider,resource_id,idempotency_key,fingerprint,status,confirmed_by,"
        "occurred_at) "
        "VALUES ('earlier-audit','CREATE_CALENDAR_EVENT','GOOGLE_CALENDAR',?,'earlier-key',?,"
        "'PLANNED','synthetic-reviewer',?)",
        (plan_id, fingerprint, (_NOW - timedelta(days=1)).isoformat()),
    )
    _service_refused(history)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wire_contract_version", "unreviewed-wire-version"),
        ("account_label", "Display Name <candidate@example.test>"),
    ],
)
def test_calendar_encrypted_plan_semantics_remain_fail_closed_with_matching_fingerprint(
    history: _HistoryRestore, field: str, value: str
) -> None:
    adapter = FixtureCalendarProvider(_PROVIDER)
    with history.session() as session:
        service = _calendar_service(session, history, adapter)
        plan = _calendar_plan(service, _PROVIDER)
        tampered = plan.model_copy(update={field: value})
        fingerprint = service._calendar_plan_fingerprint(tampered)
    with closing(sqlite3.connect(history.database)) as connection:
        envelope = connection.execute(
            "SELECT encrypted_payload FROM calendar_mutation_plans WHERE id=?", (plan.id,)
        ).fetchone()[0]
    payload = history.cipher.decrypt_json(envelope, context=f"calendar-plan:{plan.id}:payload")
    payload[field] = value
    _sql(
        history.database,
        "UPDATE calendar_mutation_plans SET encrypted_payload=?, fingerprint=? WHERE id=?",
        (
            history.cipher.encrypt_json(payload, context=f"calendar-plan:{plan.id}:payload"),
            fingerprint,
            plan.id,
        ),
    )
    _service_refused(history)


def test_calendar_plan_rejects_noncalendar_provider_with_matching_fingerprint(
    history: _HistoryRestore,
) -> None:
    adapter = FixtureCalendarProvider(_PROVIDER)
    with history.session() as session:
        service = _calendar_service(session, history, adapter)
        plan = _calendar_plan(service, _PROVIDER)
        tampered = plan.model_copy(update={"provider": IntegrationProvider.GMAIL})
        fingerprint = service._calendar_plan_fingerprint(tampered)
    _sql(
        history.database,
        "UPDATE calendar_mutation_plans SET provider='GMAIL',fingerprint=? WHERE id=?",
        (fingerprint, plan.id),
    )
    _service_refused(history)


@pytest.mark.parametrize(
    ("kind", "include_prior"),
    [
        (MutationKind.CREATE_CALENDAR_EVENT, True),
        (MutationKind.UPDATE_CALENDAR_EVENT, False),
    ],
)
def test_legacy_calendar_plan_kind_and_prior_shape_must_agree(
    history: _HistoryRestore, kind: MutationKind, include_prior: bool
) -> None:
    event = CalendarEventSnapshot(
        provider_event_id="legacy-provider-event",
        title="Legacy calendar title",
        start_at=_NOW,
        end_at=_NOW + timedelta(hours=1),
        time_zone="UTC",
    )
    prior = event if include_prior else None
    plan_id = f"legacy-{kind.value.casefold()}"
    fingerprint_payload = {
        "id": plan_id,
        "provider": _PROVIDER.value,
        "workflow_id": None,
        "event": event.model_dump(mode="json"),
        "prior_event": prior.model_dump(mode="json") if prior else None,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    with history.session() as session:
        CommunicationRepository(session, history.cipher).save_calendar_plan(
            CalendarMutationPlan(
                id=plan_id,
                provider=_PROVIDER,
                event=event,
                prior_event=prior,
                kind=kind,
                fingerprint=fingerprint,
                created_at=_NOW,
            )
        )
    _service_refused(history)


@pytest.mark.parametrize(
    ("status", "provider_id", "error_code"),
    [
        ("ACCEPTED", "fixture-event-1", None),
        ("PLANNED", "fixture-event-1", None),
        ("PLANNED", None, "UnexpectedError"),
        ("CONFIRMED", None, None),
        ("CONFIRMED", "bad\nprovider-id", None),
        ("CONFIRMED", "fixture-event-1", "UnexpectedError"),
        ("FAILED", "fixture-event-1", "ProviderCalendarNotAppliedError"),
        ("FAILED", None, None),
        ("FAILED", None, "bad\nerror"),
        ("UNCERTAIN", None, None),
    ],
)
def test_calendar_attempt_status_fields_have_one_safe_shape(
    history: _HistoryRestore,
    status: str,
    provider_id: str | None,
    error_code: str | None,
) -> None:
    _plan_id, audit_id, _fingerprint = _seed_calendar_attempt(history)
    _sql(
        history.database,
        "UPDATE communication_mutation_audits "
        "SET status=?, provider_resource_id=?, error_code=? WHERE id=?",
        (status, provider_id, error_code, audit_id),
    )
    _service_refused(history)


@pytest.mark.parametrize("table", _CACHES)
@pytest.mark.parametrize("difference", ["current-only", "staged-only", "changed", "same"])
def test_cache_only_snapshots_trigger_exact_set_preservation(
    history: _HistoryRestore, table: str, difference: str
) -> None:
    column, context = _seed_cache(history, table)
    staged = history.root / "staged.db"
    shutil.copyfile(history.database, staged)
    if difference == "current-only":
        _sql(staged, f'DELETE FROM "{table}"')
    elif difference == "staged-only":
        _sql(history.database, f'DELETE FROM "{table}"')
    elif difference == "changed":
        _sql(
            staged,
            f'UPDATE "{table}" SET "{column}"=?',
            (history.cipher.encrypt_json({"synthetic-cache": "changed"}, context=context),),
        )
    assert (
        inspection.inspect_history(staged).has_history
        or inspection.inspect_history(history.database).has_history
    )
    if difference == "same":
        before = _snapshot_bytes(history.database, staged)
        _service(history, staged)
        assert _snapshot_bytes(history.database, staged) == before
    else:
        _service_refused(history, staged, message="lose or change recorded history")


@pytest.mark.parametrize("table", _CACHES)
@pytest.mark.parametrize("damage", ["invalid-envelope", "wrong-context"])
def test_cache_only_identical_snapshots_still_authenticate_ciphertext(
    history: _HistoryRestore, table: str, damage: str
) -> None:
    column, _context = _seed_cache(history, table)
    envelope = (
        "synthetic-cache-invalid-ciphertext"
        if damage == "invalid-envelope"
        else history.cipher.encrypt_json({"synthetic-cache": "data"}, context="incorrect-context")
    )
    _sql(history.database, f'UPDATE "{table}" SET "{column}"=?', (envelope,))
    staged = history.root / "staged.db"
    shutil.copyfile(history.database, staged)
    _service_refused(history, staged)


@pytest.mark.parametrize(
    "plaintext",
    [
        b"not-json",
        b"[]",
        b'{"duplicate":1,"duplicate":2}',
        b'{"overflow":1e999}',
        b'{"nested":' * 34 + b"0" + b"}" * 34,
        b'{"nested":' * 10_000 + b"0" + b"}" * 10_000,
    ],
    ids=["invalid-json", "not-object", "duplicate-key", "nonfinite", "depth", "parser-recursion"],
)
def test_authenticated_encrypted_json_is_bounded_and_errors_are_sanitized(
    history: _HistoryRestore, plaintext: bytes
) -> None:
    column, context = _seed_cache(history, "ai_cache")
    _sql(
        history.database,
        f'UPDATE ai_cache SET "{column}"=?',
        (history.cipher.encrypt_bytes(plaintext, context=context),),
    )
    _service_refused(history)


@pytest.mark.parametrize("side", ["current", "staged-only"])
@pytest.mark.parametrize(
    "field", ["encrypted_resource", "lease_until", "next_attempt_at", "reason"]
)
def test_deleted_media_requires_a_consistent_terminal_record_on_both_sides(
    history: _HistoryRestore, side: str, field: str
) -> None:
    pristine = history.root / "pristine.db"
    shutil.copyfile(history.database, pristine)
    with history.media() as repository:
        record = _close_media(repository, _media_intent(repository), "DELETION_CONFIRMED")
    if field == "encrypted_resource":
        value = history.cipher.encrypt_json(
            {"resource_name": "files/synthetic-still-owned"},
            context=f"ai-media:{record.id}:{record.provider_id}:{record.account_fingerprint}",
        )
    elif field == "reason":
        value = "UNRESOLVED_SYNTHETIC_RESOURCE"
    else:
        value = _NOW.isoformat()
    _sql(history.database, f'UPDATE ai_media_cleanup SET "{field}"=?', (value,))
    staged = None
    if side == "staged-only":
        staged = history.root / "staged.db"
        shutil.copyfile(history.database, staged)
        shutil.copyfile(pristine, history.database)
        assert not inspection.inspect_history(history.database).has_history
    _service_refused(history, staged)
