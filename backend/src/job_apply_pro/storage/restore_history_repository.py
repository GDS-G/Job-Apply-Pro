"""Bounded read-only inspection; no ORM bootstrap, migration, merge or network."""

import json
import math
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from job_apply_pro.domain.browser import BrowserAction, BrowserObservation
from job_apply_pro.domain.challenges import ChallengeSessionSnapshot
from job_apply_pro.domain.external_effects import (
    TERMINAL_EXTERNAL_EFFECT_STATUSES,
    ExternalEffectAttempt,
    ExternalEffectKind,
    ExternalEffectOperation,
    ExternalEffectStatus,
)
from job_apply_pro.storage.restore_history_policy import (
    COMPATIBLE_EXTRA_INDEXES,
    ENUM_FIELDS,
    INDEXES,
    LEGACY_EMPTY_REVISIONS,
    MIGRATION_DEFAULTS,
    MODERN_REVISION,
    OPERATIONAL_TABLES,
    ROOTS,
    TABLES,
    UNIQUES,
    Column,
    Table,
    sqlite_declaration,
)

MAX_ROWS = 10_000
MAX_TOTAL_ROWS = 100_000
MAX_TOTAL_BYTES = 134_217_728
MAX_CELL_BYTES = 8_388_608
INSPECTION_SECONDS = 10.0
UNAVAILABLE = (
    "Restore history cannot be verified within the supported schema and inspection limits; "
    "preserve the original workspace and use a compatible complete backup"
)


class RestoreHistoryError(ValueError):
    """Only static safe errors cross the offline restore boundary."""


type Value = str | int | float | None
type Row = dict[str, Value]
type Rows = dict[tuple[Value, ...], Row]


@dataclass(frozen=True)
class HistorySnapshot:
    revision: str
    tables: dict[str, Rows]

    @property
    def has_history(self) -> bool:
        return any(self.tables.get(name) for name in ROOTS)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RestoreHistoryError(UNAVAILABLE)
        result[key] = value
    return result


def checked_json(value: str) -> object:
    def constant(_value: str) -> object:
        raise RestoreHistoryError(UNAVAILABLE)

    parsed: object = json.loads(value, object_pairs_hook=_pairs, parse_constant=constant)
    pending: list[tuple[object, int]] = [(parsed, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 50_000 or depth > 32:
            raise RestoreHistoryError(UNAVAILABLE)
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise RestoreHistoryError(UNAVAILABLE)
    return parsed


def _value(value: object, column: Column) -> Value:
    if value is None:
        if not column.nullable:
            raise RestoreHistoryError(UNAVAILABLE)
        return None
    if column.kind in {"integer", "boolean"}:
        if type(value) is not int or (column.kind == "boolean" and value not in {0, 1}):
            raise RestoreHistoryError(UNAVAILABLE)
        if (
            column.name
            in {
                "sequence",
                "revision",
                "version",
                "attempts",
                "retry_count",
                "input_tokens",
                "output_tokens",
                "cost_micros",
                "latency_ms",
                "page_count",
                "character_count",
                "answer_revision",
            }
            and value < 0
        ):
            raise RestoreHistoryError(UNAVAILABLE)
        return value
    if column.kind == "float":
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise RestoreHistoryError(UNAVAILABLE)
        return value
    if not isinstance(value, str) or len(value) > column.limit:
        raise RestoreHistoryError(UNAVAILABLE)
    if len(value.encode("utf-8")) > MAX_CELL_BYTES:
        raise RestoreHistoryError(UNAVAILABLE)
    if column.kind == "json":
        checked_json(value)
    elif column.kind == "datetime":
        datetime.fromisoformat(value)
    elif column.kind == "date":
        date.fromisoformat(value)
    return value


def _index_columns(database: sqlite3.Connection, name: str) -> tuple[str, ...]:
    rows = database.execute("SELECT * FROM pragma_index_xinfo(?)", (name,)).fetchall()
    columns: list[str] = []
    for row in rows:
        if len(row) != 6:
            raise RestoreHistoryError(UNAVAILABLE)
        sequence, column_id, column, descending, collation, key = row
        if key == 0:
            if (column_id, column, descending, collation) != (-1, None, 0, "BINARY"):
                raise RestoreHistoryError(UNAVAILABLE)
            continue
        if (
            key != 1
            or sequence != len(columns)
            or not isinstance(column_id, int)
            or column_id < 0
            or not isinstance(column, str)
            or descending != 0
            or collation != "BINARY"
        ):
            raise RestoreHistoryError(UNAVAILABLE)
        columns.append(column)
    if not columns:
        raise RestoreHistoryError(UNAVAILABLE)
    return tuple(columns)


def _validate_physical_schema(
    database: sqlite3.Connection,
    name: str,
    spec: Table,
    columns: tuple[Column, ...],
    revision: str,
) -> None:
    """Match reviewed SQLite storage semantics before selecting any row."""
    table_rows = database.execute("SELECT * FROM pragma_table_list(?)", (name,)).fetchall()
    if table_rows != [("main", name, "table", len(columns), 0, 0)]:
        raise RestoreHistoryError(UNAVAILABLE)

    actual_columns = database.execute("SELECT * FROM pragma_table_xinfo(?)", (name,)).fetchall()
    if len(actual_columns) != len(columns):
        raise RestoreHistoryError(UNAVAILABLE)
    expected = {column.name: column for column in columns}
    seen: set[str] = set()
    for column_id, column_name, declared_type, not_null, default, primary, hidden in actual_columns:
        if (
            column_id not in range(len(columns))
            or not isinstance(column_name, str)
            or column_name in seen
            or column_name not in expected
            or not isinstance(declared_type, str)
            or hidden != 0
        ):
            raise RestoreHistoryError(UNAVAILABLE)
        descriptor = expected[column_name]
        primary_position = spec.key.index(column_name) + 1 if column_name in spec.key else 0
        if (
            declared_type.upper() != sqlite_declaration(descriptor)
            or not_null != int(not descriptor.nullable)
            or default not in MIGRATION_DEFAULTS.get((name, column_name), frozenset((None,)))
            or primary != primary_position
        ):
            raise RestoreHistoryError(UNAVAILABLE)
        seen.add(column_name)
    if seen != expected.keys():
        raise RestoreHistoryError(UNAVAILABLE)

    actual_references: list[tuple[str, str, str, str, str, str]] = []
    for foreign in database.execute("SELECT * FROM pragma_foreign_key_list(?)", (name,)).fetchall():
        if len(foreign) != 8 or foreign[1] != 0:
            raise RestoreHistoryError(UNAVAILABLE)
        actual_references.append(
            (foreign[3], foreign[2], foreign[4], foreign[5], foreign[6], foreign[7])
        )
    expected_references = [
        (column, target, target_column, "NO ACTION", "NO ACTION", "NONE")
        for column, target, target_column in spec.references
        if column in expected
    ]
    if sorted(actual_references) != sorted(expected_references):
        raise RestoreHistoryError(UNAVAILABLE)

    named: dict[str, tuple[str, ...]] = {}
    enforced_uniques: set[tuple[str, ...]] = set()
    primary_indexes = 0
    for index in database.execute("SELECT * FROM pragma_index_list(?)", (name,)).fetchall():
        if len(index) != 5:
            raise RestoreHistoryError(UNAVAILABLE)
        _sequence, index_name, unique, origin, partial = index
        if (
            not isinstance(index_name, str)
            or unique not in {0, 1}
            or origin not in {"c", "u", "pk"}
            or partial != 0
        ):
            raise RestoreHistoryError(UNAVAILABLE)
        fields = _index_columns(database, index_name)
        if origin == "c":
            if index_name in named:
                raise RestoreHistoryError(UNAVAILABLE)
            named[index_name] = fields
        elif origin == "pk":
            primary_indexes += 1
            if fields != spec.key or unique != 1:
                raise RestoreHistoryError(UNAVAILABLE)
        if unique == 1 and origin != "pk":
            enforced_uniques.add(fields)
    if primary_indexes > 1:
        raise RestoreHistoryError(UNAVAILABLE)

    required_indexes = {index.name: index.columns for index in INDEXES.get(name, ())}
    compatible_indexes = {
        index.name: index.columns for index in COMPATIBLE_EXTRA_INDEXES.get(name, ())
    }
    if (
        required_indexes.keys() - named.keys()
        or named.keys() - (required_indexes.keys() | compatible_indexes.keys())
        or any(
            fields != (required_indexes | compatible_indexes)[index_name]
            for index_name, fields in named.items()
        )
    ):
        raise RestoreHistoryError(UNAVAILABLE)

    expected_uniques = set(UNIQUES.get(name, ()))
    if revision == "20260913_0025" and name == "communication_records":
        expected_uniques = {("provider", "provider_message_id")}
    if enforced_uniques != expected_uniques:
        raise RestoreHistoryError(UNAVAILABLE)


def _inspect_history_database(database: sqlite3.Connection) -> HistorySnapshot:
    """Inspect one already-open private connection without reflecting its schema."""
    deadline = time.monotonic() + INSPECTION_SECONDS
    database.set_progress_handler(lambda: int(time.monotonic() > deadline), 2_000)
    database.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_CELL_BYTES * 2)
    database.execute("PRAGMA trusted_schema=OFF")
    database.execute("PRAGMA query_only=ON")
    if database.execute("PRAGMA quick_check(1)").fetchall() != [("ok",)]:
        raise RestoreHistoryError(UNAVAILABLE)
    schema = database.execute(
        "SELECT name, type, tbl_name, sql FROM sqlite_schema "
        "WHERE name NOT LIKE 'sqlite_%' LIMIT 1001"
    ).fetchall()
    if len(schema) > 1000:
        raise RestoreHistoryError(UNAVAILABLE)
    names: dict[str, str] = {}
    for name, kind, _owner, sql in schema:
        if not isinstance(name, str) or not isinstance(kind, str):
            raise RestoreHistoryError(UNAVAILABLE)
        if (
            kind == "trigger"
            or kind == "view"
            or (kind == "table" and (not isinstance(sql, str) or "VIRTUAL" in sql.upper().split()))
        ):
            raise RestoreHistoryError(UNAVAILABLE)
        if kind == "table":
            if name.casefold() in names:
                raise RestoreHistoryError(UNAVAILABLE)
            names[name.casefold()] = name
    if names.get("alembic_version") != "alembic_version":
        raise RestoreHistoryError(UNAVAILABLE)
    if names.keys() - (TABLES.keys() | OPERATIONAL_TABLES):
        raise RestoreHistoryError(UNAVAILABLE)
    version_columns = database.execute(
        "SELECT * FROM pragma_table_xinfo('alembic_version')"
    ).fetchall()
    version_indexes = database.execute(
        "SELECT * FROM pragma_index_list('alembic_version')"
    ).fetchall()
    if (
        database.execute("SELECT * FROM pragma_table_list('alembic_version')").fetchall()
        != [("main", "alembic_version", "table", 1, 0, 0)]
        or version_columns
        not in (
            [(0, "version_num", "VARCHAR(32)", 1, None, 0, 0)],
            [(0, "version_num", "VARCHAR(32)", 1, None, 1, 0)],
        )
        or database.execute("SELECT * FROM pragma_foreign_key_list('alembic_version')").fetchall()
        or (
            (version_columns[0][5] == 0 and bool(version_indexes))
            or (
                version_columns[0][5] == 1
                and version_indexes != [(0, "sqlite_autoindex_alembic_version_1", 1, "pk", 0)]
            )
        )
    ):
        raise RestoreHistoryError(UNAVAILABLE)
    revisions = database.execute("SELECT version_num FROM alembic_version LIMIT 2").fetchall()
    if len(revisions) != 1 or not isinstance(revisions[0][0], str):
        raise RestoreHistoryError(UNAVAILABLE)
    revision = revisions[0][0]
    if revision != MODERN_REVISION and revision not in LEGACY_EMPTY_REVISIONS:
        raise RestoreHistoryError(UNAVAILABLE)
    absent = LEGACY_EMPTY_REVISIONS.get(revision, frozenset())
    result: dict[str, Rows] = {}
    total_rows, total_bytes = 0, 0
    for name, spec in TABLES.items():
        if name in absent:
            if name in names:
                raise RestoreHistoryError(UNAVAILABLE)
            result[name] = {}
            continue
        if names.get(name) != name:
            raise RestoreHistoryError(UNAVAILABLE)
        columns = tuple(
            column
            for column in spec.columns
            if not (
                revision == "20260913_0025"
                and name == "communication_records"
                and column.name in {"source_account_key", "source_connection_fingerprint"}
            )
        )
        _validate_physical_schema(database, name, spec, columns, revision)
        rows: Rows = {}
        query = ", ".join(f'"{column.name}"' for column in columns)
        for index, values in enumerate(
            database.execute(f'SELECT {query} FROM "{name}" LIMIT ?', (MAX_ROWS + 1,))
        ):
            total_rows += 1
            if index >= MAX_ROWS or total_rows > MAX_TOTAL_ROWS or time.monotonic() > deadline:
                raise RestoreHistoryError(UNAVAILABLE)
            row = {
                column.name: _value(value, column)
                for column, value in zip(columns, values, strict=True)
            }
            total_bytes += sum(
                len(value.encode("utf-8")) if isinstance(value, str) else 8
                for value in row.values()
            )
            if total_bytes > MAX_TOTAL_BYTES:
                raise RestoreHistoryError(UNAVAILABLE)
            key = tuple(row[column] for column in spec.key)
            if any(value is None or value == "" for value in key) or key in rows:
                raise RestoreHistoryError(UNAVAILABLE)
            rows[key] = row
        for unique in UNIQUES.get(name, ()):
            seen: set[tuple[Value, ...]] = set()
            # Legacy 0025 correspondence predates account-bound identity.
            if any(field not in {column.name for column in columns} for field in unique):
                if revision != "20260913_0025" or name != "communication_records":
                    raise RestoreHistoryError(UNAVAILABLE)
                unique = ("provider", "provider_message_id")
            for row in rows.values():
                identity = tuple(row[field] for field in unique)
                if None in identity:
                    continue
                if identity in seen:
                    raise RestoreHistoryError(UNAVAILABLE)
                seen.add(identity)
        result[name] = rows
    snapshot = HistorySnapshot(revision, result)
    if revision != MODERN_REVISION and snapshot.has_history:
        raise RestoreHistoryError(
            "Legacy recorded history requires a post-upgrade complete backup; "
            "restore was not applied"
        )
    return snapshot


def inspect_history(path: Path) -> HistorySnapshot:
    """Require an explicit known revision; missing or corrupt never means empty."""
    try:
        if not path.is_file():
            raise RestoreHistoryError(UNAVAILABLE)
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1)) as database:
            return _inspect_history_database(database)
    except RestoreHistoryError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError, MemoryError):
        raise RestoreHistoryError(UNAVAILABLE) from None


def inspect_history_bytes(value: bytes) -> HistorySnapshot:
    """Inspect bounded serialized SQLite bytes without a plaintext disk copy."""
    if len(value) > 256 * 1024 * 1024:
        raise RestoreHistoryError(UNAVAILABLE)
    database = sqlite3.connect(":memory:", timeout=1)
    try:
        database.enable_load_extension(False)
        database.deserialize(value)
        del value
        return _inspect_history_database(database)
    except RestoreHistoryError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError, MemoryError):
        raise RestoreHistoryError(UNAVAILABLE) from None
    finally:
        database.close()


def require_relational_closure(snapshot: HistorySnapshot) -> None:
    """Validate explicit FK dependencies plus identities stored outside SQL FKs."""
    indices: dict[tuple[str, str], set[Value]] = {}

    def values(table: str, column: str) -> set[Value]:
        key = table, column
        if key not in indices:
            indices[key] = {row[column] for row in snapshot.tables[table].values()}
        return indices[key]

    for name, spec in TABLES.items():
        for row in snapshot.tables[name].values():
            for column_spec in spec.columns:
                choices = ENUM_FIELDS.get((name, column_spec.name))
                value = row[column_spec.name]
                if choices is not None and value is not None and value not in choices:
                    raise RestoreHistoryError(UNAVAILABLE)
            for column, target, target_column in spec.references:
                if row[column] is not None and row[column] not in values(target, target_column):
                    raise RestoreHistoryError(UNAVAILABLE)
            if (
                "workflow_id" in row
                and row["workflow_id"] is not None
                and row["workflow_id"] not in values("applications", "workflow_id")
            ):
                raise RestoreHistoryError(UNAVAILABLE)
            if (
                name in {"model_invocations", "ai_cache"}
                and row["profile_id"] is not None
                and row["profile_id"] not in values("candidate_profiles", "id")
            ):
                raise RestoreHistoryError(UNAVAILABLE)
    audits = snapshot.tables["communication_mutation_audits"]
    keys: set[Value] = set()
    for row in audits.values():
        kind = row["kind"]
        if kind == "SEND_MESSAGE":
            target = "outbound_drafts"
        elif kind in {"CREATE_CALENDAR_EVENT", "UPDATE_CALENDAR_EVENT"}:
            target = "calendar_mutation_plans"
        else:
            raise RestoreHistoryError(UNAVAILABLE)
        source = snapshot.tables[target].get((row["resource_id"],))
        if (
            source is None
            or source["provider"] != row["provider"]
            or source["fingerprint"] != row["fingerprint"]
            or (target == "calendar_mutation_plans" and source["kind"] != kind)
            or row["idempotency_key"] in keys
            or row["status"] not in {"PLANNED", "CONFIRMED", "FAILED", "ACCEPTED", "UNCERTAIN"}
        ):
            raise RestoreHistoryError(UNAVAILABLE)
        keys.add(row["idempotency_key"])
    for row in snapshot.tables["mail_send_claims"].values():
        audit = audits.get((row["audit_id"],))
        if (
            audit is None
            or audit["kind"] != "SEND_MESSAGE"
            or audit["resource_id"] != row["draft_id"]
        ):
            raise RestoreHistoryError(UNAVAILABLE)
    calendar_by_plan: dict[Value, list[Row]] = {}
    for audit in audits.values():
        if audit["kind"] in {"CREATE_CALENDAR_EVENT", "UPDATE_CALENDAR_EVENT"}:
            if audit["provider"] not in {"GOOGLE_CALENDAR", "OUTLOOK_CALENDAR"}:
                raise RestoreHistoryError(UNAVAILABLE)
            status = audit["status"]
            provider_id = audit["provider_resource_id"]
            error_code = audit["error_code"]
            if status == "PLANNED":
                valid_outcome = provider_id is None and error_code is None
            elif status == "CONFIRMED":
                valid_outcome = (
                    isinstance(provider_id, str)
                    and bool(provider_id)
                    and provider_id.isascii()
                    and all(32 < ord(character) < 127 for character in provider_id)
                    and error_code is None
                )
            elif status in {"FAILED", "UNCERTAIN"}:
                valid_outcome = (
                    provider_id is None
                    and isinstance(error_code, str)
                    and bool(error_code)
                    and error_code.isascii()
                    and all(32 < ord(character) < 127 for character in error_code)
                )
            else:
                valid_outcome = False
            if not valid_outcome:
                raise RestoreHistoryError(UNAVAILABLE)
            calendar_by_plan.setdefault(audit["resource_id"], []).append(audit)
    calendar_claims = snapshot.tables["calendar_mutation_claims"]
    for row in calendar_claims.values():
        audit = audits.get((row["audit_id"],))
        plan = snapshot.tables["calendar_mutation_plans"].get((row["plan_id"],))
        if (
            audit is None
            or plan is None
            or audit["kind"] not in {"CREATE_CALENDAR_EVENT", "UPDATE_CALENDAR_EVENT"}
            or audit["resource_id"] != row["plan_id"]
            or audit["provider"] != plan["provider"]
            or audit["kind"] != plan["kind"]
            or audit["fingerprint"] != plan["fingerprint"]
        ):
            raise RestoreHistoryError(UNAVAILABLE)
    for plan_id, attempts in calendar_by_plan.items():
        claim = calendar_claims.get((plan_id,))
        oldest = min(attempts, key=lambda row: (str(row["occurred_at"]), str(row["id"])))
        if claim is None or claim["audit_id"] != oldest["id"]:
            raise RestoreHistoryError(UNAVAILABLE)
    for row in snapshot.tables["model_invocations"].values():
        if row["status"] not in {"SUCCEEDED", "FAILED", "CACHED", "UNCERTAIN"}:
            raise RestoreHistoryError(UNAVAILABLE)
    _external_effect_ledger(snapshot)
    _ownership_closure(snapshot)
    _browser_challenge_payloads(snapshot)


def _external_effect_ledger(snapshot: HistorySnapshot) -> None:
    """Validate replay ownership and terminal evidence without trusting ORM rows."""

    def payload(row: Row) -> dict[str, object]:
        result: dict[str, object] = dict(row)
        for field in ("created_at", "updated_at", "completed_at"):
            value = row[field]
            if value is None:
                continue
            if not isinstance(value, str):
                raise RestoreHistoryError(UNAVAILABLE)
            parsed = datetime.fromisoformat(value)
            result[field] = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        return result

    try:
        operations = {
            str(row["id"]): ExternalEffectOperation.model_validate(payload(row))
            for row in snapshot.tables["external_effect_operations"].values()
        }
        attempts_by_operation: dict[str, list[ExternalEffectAttempt]] = {}
        for row in snapshot.tables["external_effect_attempts"].values():
            attempt = ExternalEffectAttempt.model_validate(payload(row))
            attempts_by_operation.setdefault(attempt.operation_id, []).append(attempt)
    except (TypeError, ValueError):
        raise RestoreHistoryError(UNAVAILABLE) from None

    for operation_id, operation in operations.items():
        attempts = sorted(
            attempts_by_operation.get(operation_id, []), key=lambda item: item.sequence
        )
        if [attempt.sequence for attempt in attempts] != list(range(1, len(attempts) + 1)):
            raise RestoreHistoryError(UNAVAILABLE)
        if any(
            attempt.status not in TERMINAL_EXTERNAL_EFFECT_STATUSES for attempt in attempts[:-1]
        ):
            raise RestoreHistoryError(UNAVAILABLE)
        last = attempts[-1] if attempts else None
        if operation.status is ExternalEffectStatus.PREPARED:
            if last is not None and last.status not in {
                ExternalEffectStatus.PREPARED,
                ExternalEffectStatus.CONFIRMED,
                ExternalEffectStatus.FAILED,
            }:
                raise RestoreHistoryError(UNAVAILABLE)
        elif operation.status is ExternalEffectStatus.DISPATCHING:
            if last is None or last.status is not ExternalEffectStatus.DISPATCHING:
                raise RestoreHistoryError(UNAVAILABLE)
        else:
            if last is None or last.status is not operation.status:
                raise RestoreHistoryError(UNAVAILABLE)
            if any(
                getattr(operation, field) != getattr(last, field)
                for field in ("result_reference", "result_fingerprint", "error_code")
            ):
                raise RestoreHistoryError(UNAVAILABLE)
        if operation.kind is ExternalEffectKind.CALENDAR_UPDATE:
            # Reserved in the enum, but no production route owns this ledger kind yet.
            raise RestoreHistoryError(UNAVAILABLE)
        for attempt in attempts:
            if attempt.status is not ExternalEffectStatus.CONFIRMED:
                continue
            reference = attempt.result_reference
            if operation.kind is ExternalEffectKind.BROWSER_ACTION:
                if (
                    reference != f"browser-action:{attempt.id}"
                    or (attempt.id,) not in snapshot.tables["browser_actions"]
                ):
                    raise RestoreHistoryError(UNAVAILABLE)
            elif reference == f"model-invocation:{attempt.id}":
                if (attempt.id,) not in snapshot.tables["model_invocations"]:
                    raise RestoreHistoryError(UNAVAILABLE)
            elif reference != f"provider-response:{attempt.id}":
                raise RestoreHistoryError(UNAVAILABLE)


def _browser_challenge_payloads(snapshot: HistorySnapshot) -> None:
    def payload(value: Value) -> object:
        if not isinstance(value, str):
            raise RestoreHistoryError(UNAVAILABLE)
        return checked_json(value)

    for row in snapshot.tables["browser_sessions"].values():
        if row["last_observation_json"] not in {None, "null"}:
            BrowserObservation.model_validate(payload(row["last_observation_json"]))
    for row in snapshot.tables["browser_actions"].values():
        BrowserAction.model_validate(payload(row["action_json"]))
        BrowserObservation.model_validate(payload(row["observation_json"]))
    for row in snapshot.tables["challenge_sessions"].values():
        record = ChallengeSessionSnapshot.model_validate(payload(row["snapshot_json"]))
        if (
            any(
                getattr(record, field) != row[field]
                for field in ("id", "workflow_id", "browser_session_id", "status")
            )
            or record.detection.kind != row["kind"]
        ):
            raise RestoreHistoryError(UNAVAILABLE)


def _ownership_closure(snapshot: HistorySnapshot) -> None:
    workflows = {row["workflow_id"]: row for row in snapshot.tables["applications"].values()}

    def get(table: str, identity: Value) -> Row:
        result = snapshot.tables[table].get((identity,))
        if result is None:
            raise RestoreHistoryError(UNAVAILABLE)
        return result

    def version_profile(identity: Value) -> Value:
        version = get("document_versions", identity)
        return get("documents", version["document_id"])["profile_id"]

    for table, rows in snapshot.tables.items():
        for row in rows.values():
            application = (
                get("applications", row["application_id"]) if "application_id" in row else None
            )
            if application is None and row.get("workflow_id") is not None:
                application = workflows[row["workflow_id"]]
            if application is not None:
                for field in ("profile_id", "job_id"):
                    if field in row and row[field] is not None and row[field] != application[field]:
                        raise RestoreHistoryError(UNAVAILABLE)
                if "workflow_id" in row and row["workflow_id"] != application["workflow_id"]:
                    raise RestoreHistoryError(UNAVAILABLE)
            profile = row.get("profile_id") or (application["profile_id"] if application else None)
            for field in ("document_version_id", "selected_document_version_id"):
                if (
                    row.get(field) is not None
                    and profile is not None
                    and version_profile(row[field]) != profile
                ):
                    raise RestoreHistoryError(UNAVAILABLE)
            for target, field in (
                ("evidence_sources", "evidence_source_id"),
                ("candidate_claims", "superseded_by_id"),
            ):
                if (
                    table == "candidate_claims"
                    and row[field] is not None
                    and get(target, row[field])["profile_id"] != profile
                ):
                    raise RestoreHistoryError(UNAVAILABLE)
            if (
                table == "answer_library_revisions"
                and get("answer_library", row["answer_id"])["profile_id"] != profile
            ):
                raise RestoreHistoryError(UNAVAILABLE)
            for field in ("source_answer_id", "library_answer_id"):
                if (
                    table == "application_answers"
                    and row[field] is not None
                    and get("answer_library", row[field])["profile_id"] != profile
                ):
                    raise RestoreHistoryError(UNAVAILABLE)
            if (
                table == "document_selection_audits"
                and get("document_versions", row["document_version_id"])["document_id"]
                != row["document_id"]
            ):
                raise RestoreHistoryError(UNAVAILABLE)
            if table == "submitted_document_evidence":
                version = get("document_versions", row["document_version_id"])
                if any(row[field] != version[field] for field in ("sha256", "file_name")):
                    raise RestoreHistoryError(UNAVAILABLE)
            if table == "retrieval_chunks":
                retrieval_target = {"CLAIM": "candidate_claims", "ANSWER": "answer_library"}.get(
                    str(row["source_type"])
                )
                if (
                    retrieval_target is None
                    or get(retrieval_target, row["source_id"])["profile_id"] != profile
                ):
                    raise RestoreHistoryError(UNAVAILABLE)
            if table == "application_answers":
                encoded_results = row["retrieval_results_json"]
                if not isinstance(encoded_results, str):
                    raise RestoreHistoryError(UNAVAILABLE)
                results = checked_json(encoded_results)
                if not isinstance(results, list):
                    raise RestoreHistoryError(UNAVAILABLE)
                for result in results:
                    if not isinstance(result, dict) or not isinstance(result.get("source_id"), str):
                        raise RestoreHistoryError(UNAVAILABLE)
                    source_type = result.get("source_type")
                    retrieval_target = {
                        "CLAIM": "candidate_claims",
                        "ANSWER": "answer_library",
                    }.get(str(source_type))
                    if (
                        retrieval_target is None
                        or get(retrieval_target, result["source_id"])["profile_id"] != profile
                    ):
                        raise RestoreHistoryError(UNAVAILABLE)
            if "application_answer_id" in row:
                answer = get("application_answers", row["application_answer_id"])
                if answer["application_id"] != row["application_id"]:
                    raise RestoreHistoryError(UNAVAILABLE)
                # Older execution records legitimately point to an earlier answer revision.
                if not isinstance(row["answer_revision"], int) or not isinstance(
                    answer["revision"], int
                ):
                    raise RestoreHistoryError(UNAVAILABLE)
                if row["answer_revision"] > answer["revision"]:
                    raise RestoreHistoryError(UNAVAILABLE)
            if table == "application_field_executions":
                binding = get("application_field_bindings", row["binding_id"])
                run = get("supervised_portal_runs", row["supervised_run_id"])
                if any(
                    binding[field] != row[field]
                    for field in ("application_id", "application_answer_id")
                ):
                    raise RestoreHistoryError(UNAVAILABLE)
                if run["browser_session_id"] != row["browser_session_id"]:
                    raise RestoreHistoryError(UNAVAILABLE)
                if application is None or run["workflow_id"] != application["workflow_id"]:
                    raise RestoreHistoryError(UNAVAILABLE)
            if "browser_session_id" in row:
                browser = get("browser_sessions", row["browser_session_id"])
                workflow = row.get("workflow_id") or (
                    application["workflow_id"] if application else None
                )
                if workflow is not None and browser["workflow_id"] != workflow:
                    raise RestoreHistoryError(UNAVAILABLE)
            for field, target in (
                ("evidence_claim_ids_json", "candidate_claims"),
                ("document_version_ids_json", "document_versions"),
                ("requirement_ids_json", "job_requirements"),
            ):
                if field not in row:
                    continue
                encoded = row[field]
                if not isinstance(encoded, str):
                    raise RestoreHistoryError(UNAVAILABLE)
                identities = checked_json(encoded)
                if not isinstance(identities, list) or any(
                    not isinstance(item, str) for item in identities
                ):
                    raise RestoreHistoryError(UNAVAILABLE)
                if table == "outbound_drafts" and identities and profile is None:
                    raise RestoreHistoryError(UNAVAILABLE)
                for identity in identities:
                    linked = get(target, identity)
                    owner = (
                        version_profile(identity)
                        if target == "document_versions"
                        else linked.get("profile_id")
                    )
                    if profile is not None and owner is not None and owner != profile:
                        raise RestoreHistoryError(UNAVAILABLE)
                    if target == "job_requirements" and linked["job_id"] != row.get("job_id"):
                        raise RestoreHistoryError(UNAVAILABLE)
