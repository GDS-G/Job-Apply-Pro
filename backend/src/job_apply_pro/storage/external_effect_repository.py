from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_apply_pro.domain.external_effects import (
    TERMINAL_EXTERNAL_EFFECT_STATUSES,
    ExternalEffectAdmission,
    ExternalEffectAttempt,
    ExternalEffectKind,
    ExternalEffectMetrics,
    ExternalEffectOperation,
    ExternalEffectPublicRecord,
    ExternalEffectRecord,
    ExternalEffectStatus,
)
from job_apply_pro.storage.models import ExternalEffectAttemptRow, ExternalEffectOperationRow

_UNRESOLVED = {
    ExternalEffectStatus.PREPARED.value,
    ExternalEffectStatus.DISPATCHING.value,
    ExternalEffectStatus.UNCERTAIN.value,
}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ExternalEffectConflictError(RuntimeError):
    """A durable effect claim or state changed and cannot be retried safely."""


class ExternalEffectRepository:
    """Independent, committed transitions for effects that cross a process boundary."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        with self._session_factory() as session:
            try:
                if session.get_bind().dialect.name == "sqlite":
                    session.execute(text("BEGIN IMMEDIATE"))
                else:
                    session.connection(execution_options={"isolation_level": "SERIALIZABLE"})
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def prepare_operation(
        self,
        *,
        claim_fingerprint: str,
        kind: ExternalEffectKind,
        subject_type: str,
        subject_id: str,
        actor: str,
        request_fingerprint: str,
        policy_version: str,
        now: datetime,
    ) -> ExternalEffectAdmission:
        candidate = ExternalEffectOperation(
            id=str(uuid4()),
            claim_fingerprint=claim_fingerprint,
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            actor=actor,
            request_fingerprint=request_fingerprint,
            policy_version=policy_version,
            status=ExternalEffectStatus.PREPARED,
            created_at=now,
            updated_at=now,
        )
        try:
            with self._transaction() as session:
                existing = session.scalar(
                    select(ExternalEffectOperationRow).where(
                        ExternalEffectOperationRow.claim_fingerprint == claim_fingerprint
                    )
                )
                if existing is not None:
                    operation = self._operation(existing)
                    self._assert_exact_operation(operation, candidate)
                    return ExternalEffectAdmission(operation=operation, created=False)
                unresolved = session.scalar(
                    select(ExternalEffectOperationRow).where(
                        ExternalEffectOperationRow.subject_type == subject_type,
                        ExternalEffectOperationRow.subject_id == subject_id,
                        ExternalEffectOperationRow.status.in_(_UNRESOLVED),
                    )
                )
                if unresolved is not None:
                    raise ExternalEffectConflictError(
                        "An unresolved external effect already owns this subject"
                    )
                session.add(
                    ExternalEffectOperationRow(
                        id=candidate.id,
                        claim_fingerprint=candidate.claim_fingerprint,
                        kind=candidate.kind.value,
                        subject_type=candidate.subject_type,
                        subject_id=candidate.subject_id,
                        actor=candidate.actor,
                        request_fingerprint=candidate.request_fingerprint,
                        policy_version=candidate.policy_version,
                        status=candidate.status.value,
                        result_reference=None,
                        result_fingerprint=None,
                        error_code=None,
                        created_at=candidate.created_at,
                        updated_at=candidate.updated_at,
                        completed_at=None,
                    )
                )
                session.flush()
            return ExternalEffectAdmission(operation=candidate, created=True)
        except IntegrityError as error:
            winner = self.get_by_claim(claim_fingerprint)
            if winner is None:
                raise ExternalEffectConflictError(
                    "External-effect admission raced and was not readable"
                ) from error
            self._assert_exact_operation(winner.operation, candidate)
            return ExternalEffectAdmission(operation=winner.operation, created=False)

    def prepare_attempt(
        self,
        operation_id: str,
        *,
        provider: str,
        target_code: str,
        request_fingerprint: str,
        native_key_fingerprint: str | None,
        now: datetime,
    ) -> ExternalEffectAttempt:
        with self._transaction() as session:
            operation = session.get(ExternalEffectOperationRow, operation_id)
            if operation is None or operation.status != ExternalEffectStatus.PREPARED.value:
                raise ExternalEffectConflictError(
                    "External effect is not prepared for a new attempt"
                )
            latest = session.scalar(
                select(func.max(ExternalEffectAttemptRow.sequence)).where(
                    ExternalEffectAttemptRow.operation_id == operation_id
                )
            )
            sequence = int(latest or 0) + 1
            attempt = ExternalEffectAttempt(
                id=str(uuid4()),
                operation_id=operation_id,
                sequence=sequence,
                provider=provider,
                target_code=target_code,
                request_fingerprint=request_fingerprint,
                native_key_fingerprint=native_key_fingerprint,
                status=ExternalEffectStatus.PREPARED,
                created_at=now,
                updated_at=now,
            )
            session.add(
                ExternalEffectAttemptRow(
                    id=attempt.id,
                    operation_id=attempt.operation_id,
                    sequence=attempt.sequence,
                    provider=attempt.provider,
                    target_code=attempt.target_code,
                    request_fingerprint=attempt.request_fingerprint,
                    native_key_fingerprint=attempt.native_key_fingerprint,
                    status=attempt.status.value,
                    result_reference=None,
                    result_fingerprint=None,
                    error_code=None,
                    input_tokens=None,
                    output_tokens=None,
                    cost_micros=None,
                    created_at=attempt.created_at,
                    updated_at=attempt.updated_at,
                    completed_at=None,
                )
            )
            session.flush()
        return attempt

    def begin_dispatch(
        self, operation_id: str, attempt_id: str, *, now: datetime
    ) -> ExternalEffectRecord:
        with self._transaction() as session:
            operation = session.get(ExternalEffectOperationRow, operation_id)
            attempt = session.get(ExternalEffectAttemptRow, attempt_id)
            if (
                operation is None
                or attempt is None
                or attempt.operation_id != operation_id
                or operation.status != ExternalEffectStatus.PREPARED.value
                or attempt.status != ExternalEffectStatus.PREPARED.value
            ):
                raise ExternalEffectConflictError("External-effect dispatch ownership changed")
            operation.status = ExternalEffectStatus.DISPATCHING.value
            operation.updated_at = now
            attempt.status = ExternalEffectStatus.DISPATCHING.value
            attempt.updated_at = now
            session.flush()
            result = self._record(session, operation)
        return result

    def finish_attempt_and_operation(
        self,
        operation_id: str,
        attempt_id: str,
        *,
        status: ExternalEffectStatus,
        now: datetime,
        result_reference: str | None = None,
        result_fingerprint: str | None = None,
        error_code: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_micros: int | None = None,
    ) -> ExternalEffectRecord:
        return self._finish(
            operation_id,
            attempt_id,
            status=status,
            now=now,
            continue_operation=False,
            result_reference=result_reference,
            result_fingerprint=result_fingerprint,
            error_code=error_code,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micros=cost_micros,
        )

    def finish_attempt_for_continuation(
        self,
        operation_id: str,
        attempt_id: str,
        *,
        status: ExternalEffectStatus,
        now: datetime,
        result_reference: str | None = None,
        result_fingerprint: str | None = None,
        error_code: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_micros: int | None = None,
    ) -> ExternalEffectRecord:
        if status not in {ExternalEffectStatus.CONFIRMED, ExternalEffectStatus.FAILED}:
            raise ValueError("Only known attempt outcomes may continue an operation")
        return self._finish(
            operation_id,
            attempt_id,
            status=status,
            now=now,
            continue_operation=True,
            result_reference=result_reference,
            result_fingerprint=result_fingerprint,
            error_code=error_code,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micros=cost_micros,
        )

    def _finish(
        self,
        operation_id: str,
        attempt_id: str,
        *,
        status: ExternalEffectStatus,
        now: datetime,
        continue_operation: bool,
        result_reference: str | None,
        result_fingerprint: str | None,
        error_code: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        cost_micros: int | None,
    ) -> ExternalEffectRecord:
        if status not in TERMINAL_EXTERNAL_EFFECT_STATUSES:
            raise ValueError("External-effect outcome must be terminal")
        outcome = {
            "status": status.value,
            "result_reference": result_reference,
            "result_fingerprint": result_fingerprint,
            "error_code": error_code,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_micros": cost_micros,
        }
        # Validate terminal field combinations before mutating a database row.
        ExternalEffectAttempt(
            id=attempt_id,
            operation_id=operation_id,
            sequence=1,
            provider="validation",
            target_code="validation",
            request_fingerprint="0" * 64,
            status=status,
            result_reference=result_reference,
            result_fingerprint=result_fingerprint,
            error_code=error_code,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micros=cost_micros,
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
        with self._transaction() as session:
            operation = session.get(ExternalEffectOperationRow, operation_id)
            attempt = session.get(ExternalEffectAttemptRow, attempt_id)
            if operation is None or attempt is None or attempt.operation_id != operation_id:
                raise ExternalEffectConflictError("External-effect terminal target was not found")
            if attempt.status in {value.value for value in TERMINAL_EXTERNAL_EFFECT_STATUSES}:
                if not self._attempt_matches(attempt, outcome):
                    raise ExternalEffectConflictError(
                        "External-effect terminal outcome is immutable"
                    )
                if continue_operation and operation.status == ExternalEffectStatus.PREPARED.value:
                    return self._record(session, operation)
                if not continue_operation and operation.status == status.value:
                    return self._record(session, operation)
                raise ExternalEffectConflictError(
                    "External-effect operation outcome is inconsistent"
                )
            if (
                operation.status != ExternalEffectStatus.DISPATCHING.value
                or attempt.status != ExternalEffectStatus.DISPATCHING.value
            ):
                raise ExternalEffectConflictError("External-effect terminal ownership changed")
            for key, value in outcome.items():
                setattr(attempt, key, value)
            attempt.updated_at = now
            attempt.completed_at = now
            if continue_operation:
                operation.status = ExternalEffectStatus.PREPARED.value
                operation.updated_at = now
            else:
                operation.status = status.value
                operation.result_reference = result_reference
                operation.result_fingerprint = result_fingerprint
                operation.error_code = error_code
                operation.updated_at = now
                operation.completed_at = now
            session.flush()
            result = self._record(session, operation)
        return result

    def recover_interrupted(self, *, now: datetime) -> int:
        recovered = 0
        with self._transaction() as session:
            operations = session.scalars(
                select(ExternalEffectOperationRow).where(
                    ExternalEffectOperationRow.status == ExternalEffectStatus.DISPATCHING.value
                )
            ).all()
            for operation in operations:
                attempts = session.scalars(
                    select(ExternalEffectAttemptRow).where(
                        ExternalEffectAttemptRow.operation_id == operation.id,
                        ExternalEffectAttemptRow.status == ExternalEffectStatus.DISPATCHING.value,
                    )
                ).all()
                if len(attempts) != 1:
                    raise ExternalEffectConflictError(
                        "Interrupted external effect has invalid active-attempt history"
                    )
                attempt = attempts[0]
                attempt.status = ExternalEffectStatus.UNCERTAIN.value
                attempt.error_code = "PROCESS_INTERRUPTED"
                attempt.updated_at = now
                attempt.completed_at = now
                operation.status = ExternalEffectStatus.UNCERTAIN.value
                operation.error_code = "PROCESS_INTERRUPTED"
                operation.updated_at = now
                operation.completed_at = now
                recovered += 1
        return recovered

    def has_unresolved_subject(self, subject_type: str, subject_id: str) -> bool:
        with self._session_factory() as session:
            return (
                session.scalar(
                    select(ExternalEffectOperationRow.id).where(
                        ExternalEffectOperationRow.subject_type == subject_type,
                        ExternalEffectOperationRow.subject_id == subject_id,
                        ExternalEffectOperationRow.status.in_(_UNRESOLVED),
                    )
                )
                is not None
            )

    def unresolved_subject_ids(self, *, kind: ExternalEffectKind, subject_type: str) -> list[str]:
        with self._session_factory() as session:
            return list(
                session.scalars(
                    select(ExternalEffectOperationRow.subject_id)
                    .where(
                        ExternalEffectOperationRow.kind == kind.value,
                        ExternalEffectOperationRow.subject_type == subject_type,
                        ExternalEffectOperationRow.status.in_(_UNRESOLVED),
                    )
                    .distinct()
                    .order_by(ExternalEffectOperationRow.subject_id)
                ).all()
            )

    def get(self, operation_id: str) -> ExternalEffectRecord | None:
        with self._session_factory() as session:
            operation = session.get(ExternalEffectOperationRow, operation_id)
            return self._record(session, operation) if operation is not None else None

    def get_by_claim(self, claim_fingerprint: str) -> ExternalEffectRecord | None:
        with self._session_factory() as session:
            operation = session.scalar(
                select(ExternalEffectOperationRow).where(
                    ExternalEffectOperationRow.claim_fingerprint == claim_fingerprint
                )
            )
            return self._record(session, operation) if operation is not None else None

    def list_public(
        self,
        *,
        kind: ExternalEffectKind | None = None,
        status: ExternalEffectStatus | None = None,
        limit: int = 100,
    ) -> list[ExternalEffectPublicRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("External-effect list limit must be between 1 and 500")
        with self._session_factory() as session:
            statement = select(ExternalEffectOperationRow).order_by(
                ExternalEffectOperationRow.created_at.desc(),
                ExternalEffectOperationRow.id.desc(),
            )
            if kind is not None:
                statement = statement.where(ExternalEffectOperationRow.kind == kind.value)
            if status is not None:
                statement = statement.where(ExternalEffectOperationRow.status == status.value)
            rows = session.scalars(statement.limit(limit)).all()
            count_rows = (
                session.execute(
                    select(
                        ExternalEffectAttemptRow.operation_id,
                        func.count(ExternalEffectAttemptRow.id),
                    )
                    .where(ExternalEffectAttemptRow.operation_id.in_([row.id for row in rows]))
                    .group_by(ExternalEffectAttemptRow.operation_id)
                ).all()
                if rows
                else []
            )
            counts: dict[str, int] = {
                operation_id: int(count) for operation_id, count in count_rows
            }
            return [self._public(row, int(counts.get(row.id, 0))) for row in rows]

    def metrics(self) -> ExternalEffectMetrics:
        with self._session_factory() as session:
            status_rows = session.execute(
                select(ExternalEffectOperationRow.status, func.count()).group_by(
                    ExternalEffectOperationRow.status
                )
            ).all()
            kind_rows = session.execute(
                select(ExternalEffectOperationRow.kind, func.count()).group_by(
                    ExternalEffectOperationRow.kind
                )
            ).all()
        by_status = {ExternalEffectStatus(key): int(value) for key, value in status_rows}
        by_kind = {ExternalEffectKind(key): int(value) for key, value in kind_rows}
        return ExternalEffectMetrics(
            total=sum(by_status.values()),
            unresolved=sum(by_status.get(ExternalEffectStatus(value), 0) for value in _UNRESOLVED),
            by_status=by_status,
            by_kind=by_kind,
        )

    @classmethod
    def _record(
        cls, session: Session, operation: ExternalEffectOperationRow
    ) -> ExternalEffectRecord:
        attempts = session.scalars(
            select(ExternalEffectAttemptRow)
            .where(ExternalEffectAttemptRow.operation_id == operation.id)
            .order_by(ExternalEffectAttemptRow.sequence)
        ).all()
        return ExternalEffectRecord(
            operation=cls._operation(operation),
            attempts=[cls._attempt(row) for row in attempts],
        )

    @staticmethod
    def _operation(row: ExternalEffectOperationRow) -> ExternalEffectOperation:
        return ExternalEffectOperation(
            id=row.id,
            claim_fingerprint=row.claim_fingerprint,
            kind=ExternalEffectKind(row.kind),
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            actor=row.actor,
            request_fingerprint=row.request_fingerprint,
            policy_version=row.policy_version,
            status=ExternalEffectStatus(row.status),
            result_reference=row.result_reference,
            result_fingerprint=row.result_fingerprint,
            error_code=row.error_code,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
            completed_at=_utc(row.completed_at),
        )

    @staticmethod
    def _attempt(row: ExternalEffectAttemptRow) -> ExternalEffectAttempt:
        return ExternalEffectAttempt(
            id=row.id,
            operation_id=row.operation_id,
            sequence=row.sequence,
            provider=row.provider,
            target_code=row.target_code,
            request_fingerprint=row.request_fingerprint,
            native_key_fingerprint=row.native_key_fingerprint,
            status=ExternalEffectStatus(row.status),
            result_reference=row.result_reference,
            result_fingerprint=row.result_fingerprint,
            error_code=row.error_code,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cost_micros=row.cost_micros,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
            completed_at=_utc(row.completed_at),
        )

    @staticmethod
    def _public(row: ExternalEffectOperationRow, attempt_count: int) -> ExternalEffectPublicRecord:
        return ExternalEffectPublicRecord(
            id=row.id,
            kind=ExternalEffectKind(row.kind),
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            status=ExternalEffectStatus(row.status),
            result_reference=row.result_reference,
            error_code=row.error_code,
            attempt_count=attempt_count,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
            completed_at=_utc(row.completed_at),
        )

    @staticmethod
    def _assert_exact_operation(
        existing: ExternalEffectOperation, candidate: ExternalEffectOperation
    ) -> None:
        fields = (
            "claim_fingerprint",
            "kind",
            "subject_type",
            "subject_id",
            "actor",
            "request_fingerprint",
            "policy_version",
        )
        if any(getattr(existing, field) != getattr(candidate, field) for field in fields):
            raise ExternalEffectConflictError("External-effect claim was reused for different work")

    @staticmethod
    def _attempt_matches(row: ExternalEffectAttemptRow, outcome: Mapping[str, object]) -> bool:
        return all(getattr(row, key) == value for key, value in outcome.items())
