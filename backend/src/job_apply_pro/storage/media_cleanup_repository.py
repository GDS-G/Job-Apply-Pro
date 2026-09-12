from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from job_apply_pro.domain.media_cleanup import (
    MediaCleanupPublicRecord,
    MediaCleanupRecord,
    MediaCleanupState,
)
from job_apply_pro.security.encryption import DecryptionError, SensitiveDataCipher
from job_apply_pro.security.keys import KeyConfigurationError
from job_apply_pro.storage.models import MediaCleanupRow

_FILE_NAME = re.compile(r"^files/[a-z0-9-]{1,40}$")
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_ACTIVE = {MediaCleanupState.UPLOADING.value, MediaCleanupState.IN_USE.value}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class MediaCleanupConflict(RuntimeError):  # noqa: N818 - shared cleanup boundary contract
    """Ownership or retention preconditions no longer permit this operation."""


class MediaCleanupRepository:
    """Committed, independent transactions for encrypted remote-media ownership.

    No transaction spans provider I/O. SQLite BEGIN IMMEDIATE serializes the account
    admission check and every conditional ownership transition across processes.
    """

    def __init__(self, session_factory: Callable[[], Session], cipher: SensitiveDataCipher) -> None:
        self._session_factory = session_factory
        self._cipher = cipher

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        with self._session_factory() as session:
            try:
                if session.get_bind().dialect.name == "sqlite":
                    session.execute(text("BEGIN IMMEDIATE"))
                else:
                    # A predicate lock is needed even when the account has no rows yet.
                    session.connection(execution_options={"isolation_level": "SERIALIZABLE"})
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def create(
        self,
        provider_id: str,
        account_fingerprint: str,
        owner_token: str,
        now: datetime,
        lease_until: datetime,
    ) -> MediaCleanupRecord:
        if not provider_id or len(provider_id) > 80:
            raise ValueError("Media cleanup provider identity is invalid")
        if not re.fullmatch(r"[a-f0-9]{64}", account_fingerprint):
            raise ValueError("Media cleanup account fingerprint is invalid")
        if not owner_token or len(owner_token) > 80:
            raise ValueError("Media cleanup ownership token is invalid")
        self._validate_lease(now, lease_until)
        with self._transaction() as session:
            unresolved = session.scalars(
                select(MediaCleanupRow).where(
                    MediaCleanupRow.account_fingerprint == account_fingerprint,
                    MediaCleanupRow.state != MediaCleanupState.DELETED.value,
                )
            ).all()
            if any(
                row.owner_token != owner_token
                or row.state not in _ACTIVE
                or row.lease_until is None
                or _utc(row.lease_until) <= _utc(now)
                for row in unresolved
            ):
                raise MediaCleanupConflict("Unresolved media blocks this credential identity")
            row = MediaCleanupRow(
                id=str(uuid4()),
                provider_id=provider_id,
                account_fingerprint=account_fingerprint,
                owner_token=owner_token,
                state=MediaCleanupState.UPLOADING.value,
                encrypted_resource=None,
                attempts=0,
                reason=None,
                lease_until=lease_until,
                next_attempt_at=None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            result = self._record(row)
        return result

    def register_resource(
        self,
        id: str,
        token: str,
        name: str,
        now: datetime,
        lease_until: datetime,
    ) -> MediaCleanupRecord:
        if not _FILE_NAME.fullmatch(name):
            raise ValueError("Media cleanup resource name is invalid")
        self._validate_lease(now, lease_until)
        with self._transaction() as session:
            row = self._owned(session, id, token, {MediaCleanupState.UPLOADING.value}, now)
            row.encrypted_resource = self._cipher.encrypt_json(
                {"resource_name": name}, context=self._context(row)
            )
            row.state = MediaCleanupState.IN_USE.value
            row.lease_until = lease_until
            row.updated_at = now
            result = self._record(row, resource_name=name)
        return result

    def renew(
        self, id: str, token: str, now: datetime, lease_until: datetime
    ) -> MediaCleanupRecord:
        self._validate_lease(now, lease_until)
        with self._transaction() as session:
            row = self._owned(
                session, id, token, _ACTIVE | {MediaCleanupState.DELETE_PENDING.value}, now
            )
            row.lease_until = lease_until
            row.updated_at = now
            result = self._record(row)
        return result

    def abandon_before_upload(self, id: str, token: str, now: datetime) -> MediaCleanupRecord:
        """Close an intent only when the caller knows no media bytes were transmitted."""
        with self._transaction() as session:
            row = self._owned(session, id, token, {MediaCleanupState.UPLOADING.value}, now)
            if row.encrypted_resource is not None:
                raise MediaCleanupConflict("Known media cannot be closed as not uploaded")
            row.state = MediaCleanupState.DELETED.value
            row.reason = "NOT_UPLOADED"
            row.lease_until = None
            row.next_attempt_at = None
            row.updated_at = now
            result = self._record(row)
        return result

    def relinquish(self, id: str, token: str, now: datetime) -> MediaCleanupRecord:
        with self._transaction() as session:
            row = self._owned(session, id, token, _ACTIVE, now)
            row.state = (
                MediaCleanupState.DELETE_PENDING.value
                if row.encrypted_resource is not None
                else MediaCleanupState.MANUAL_REVIEW.value
            )
            row.reason = "DELETION_REQUIRED" if row.encrypted_resource else "UNKNOWN_UPLOAD"
            row.lease_until = None
            row.next_attempt_at = now if row.encrypted_resource else None
            row.updated_at = now
            result = self._record(row)
        return result

    def claim_recovery(
        self, id: str, token: str, now: datetime, lease_until: datetime
    ) -> MediaCleanupRecord | None:
        self._validate_lease(now, lease_until)
        if not token or len(token) > 80:
            raise ValueError("Media cleanup ownership token is invalid")
        with self._transaction() as session:
            row = session.get(MediaCleanupRow, id)
            if row is None or not self._eligible(row, now):
                return None
            row.owner_token = token
            row.updated_at = now
            row.next_attempt_at = None
            if row.encrypted_resource is None:
                row.state = MediaCleanupState.MANUAL_REVIEW.value
                row.reason = "UNKNOWN_UPLOAD"
                row.lease_until = None
                result = self._record(row)
            else:
                try:
                    resource_name = self._resource(row)
                except (DecryptionError, KeyConfigurationError, ValueError, TypeError):
                    row.state = MediaCleanupState.MANUAL_REVIEW.value
                    row.reason = "UNREADABLE_RESOURCE"
                    row.lease_until = None
                    result = self._record(row)
                else:
                    row.state = MediaCleanupState.DELETE_PENDING.value
                    row.reason = "DELETION_REQUIRED"
                    row.lease_until = lease_until
                    result = self._record(row, resource_name=resource_name)
        return result

    def mark_deleted(self, id: str, token: str, now: datetime) -> MediaCleanupRecord:
        with self._transaction() as session:
            row = self._owned(session, id, token, {MediaCleanupState.DELETE_PENDING.value}, now)
            if row.encrypted_resource is None:
                raise MediaCleanupConflict("Unknown media cannot be confirmed deleted")
            row.state = MediaCleanupState.DELETED.value
            row.reason = "DELETION_CONFIRMED"
            row.encrypted_resource = None
            row.lease_until = None
            row.next_attempt_at = None
            row.updated_at = now
            result = self._record(row)
        return result

    def mark_retry(
        self,
        id: str,
        token: str,
        reason: str,
        now: datetime,
        next_attempt_at: datetime,
    ) -> MediaCleanupRecord:
        if not _REASON.fullmatch(reason):
            raise ValueError("Media cleanup reason must be a safe internal code")
        if _utc(next_attempt_at) < _utc(now):
            raise ValueError("Media cleanup retry cannot be scheduled in the past")
        with self._transaction() as session:
            row = self._owned(session, id, token, {MediaCleanupState.DELETE_PENDING.value}, now)
            row.attempts += 1
            row.reason = reason
            row.lease_until = None
            row.next_attempt_at = next_attempt_at
            row.updated_at = now
            result = self._record(row)
        return result

    def resolve_manual(
        self, id: str, expected_updated_at: datetime, now: datetime
    ) -> MediaCleanupRecord:
        with self._transaction() as session:
            row = session.get(MediaCleanupRow, id)
            if (
                row is None
                or row.state != MediaCleanupState.MANUAL_REVIEW.value
                or row.encrypted_resource is not None
                or _utc(row.updated_at) != _utc(expected_updated_at)
            ):
                raise MediaCleanupConflict("Media cleanup manual review changed or is not allowed")
            row.state = MediaCleanupState.DELETED.value
            # This is a user-reviewed local closure, not an observed provider deletion.
            row.reason = "MANUALLY_REVIEWED"
            row.lease_until = None
            row.next_attempt_at = None
            row.updated_at = now
            result = self._record(row)
        return result

    def list_public(self) -> list[MediaCleanupPublicRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(MediaCleanupRow)
                .where(MediaCleanupRow.state != MediaCleanupState.DELETED.value)
                .order_by(MediaCleanupRow.created_at, MediaCleanupRow.id)
            ).all()
            return [
                MediaCleanupPublicRecord.model_validate(self._public_values(row)) for row in rows
            ]

    def list_recovery_candidates(
        self,
        now: datetime,
        limit: int = 100,
        *,
        accounts: set[str] | None = None,
        include_unknown: bool = False,
    ) -> list[MediaCleanupRecord]:
        if not 1 <= limit <= 1000:
            raise ValueError("Media cleanup recovery limit must be between 1 and 1000")
        if accounts == set() and not include_unknown:
            return []
        with self._session_factory() as session:
            statement = (
                select(MediaCleanupRow)
                .where(
                    or_(
                        and_(
                            MediaCleanupRow.state.in_(_ACTIVE),
                            or_(
                                MediaCleanupRow.lease_until.is_(None),
                                MediaCleanupRow.lease_until <= now,
                            ),
                        ),
                        and_(
                            MediaCleanupRow.state == MediaCleanupState.DELETE_PENDING.value,
                            or_(
                                MediaCleanupRow.lease_until.is_(None),
                                MediaCleanupRow.lease_until <= now,
                            ),
                            or_(
                                MediaCleanupRow.next_attempt_at.is_(None),
                                MediaCleanupRow.next_attempt_at <= now,
                            ),
                        ),
                    )
                )
                .order_by(MediaCleanupRow.updated_at, MediaCleanupRow.id)
                .limit(limit)
            )
            if accounts is not None:
                account_match = MediaCleanupRow.account_fingerprint.in_(sorted(accounts))
                statement = statement.where(
                    or_(account_match, MediaCleanupRow.encrypted_resource.is_(None))
                    if include_unknown
                    else account_match
                )
            rows = session.scalars(statement).all()
            return [self._record(row) for row in rows]

    @staticmethod
    def _validate_lease(now: datetime, lease_until: datetime) -> None:
        if _utc(lease_until) <= _utc(now):
            raise ValueError("Media cleanup lease must end in the future")

    @staticmethod
    def _eligible(row: MediaCleanupRow, now: datetime) -> bool:
        lease_expired = row.lease_until is None or _utc(row.lease_until) <= _utc(now)
        if row.state in _ACTIVE:
            return lease_expired
        return (
            row.state == MediaCleanupState.DELETE_PENDING.value
            and lease_expired
            and (row.next_attempt_at is None or _utc(row.next_attempt_at) <= _utc(now))
        )

    @staticmethod
    def _owned(
        session: Session, id: str, token: str, states: set[str], now: datetime
    ) -> MediaCleanupRow:
        row = session.get(MediaCleanupRow, id)
        if (
            row is None
            or row.owner_token != token
            or row.state not in states
            or row.lease_until is None
            or _utc(row.lease_until) <= _utc(now)
        ):
            raise MediaCleanupConflict("Media cleanup ownership changed or expired")
        return row

    @staticmethod
    def _context(row: MediaCleanupRow) -> str:
        return f"ai-media:{row.id}:{row.provider_id}:{row.account_fingerprint}"

    def _resource(self, row: MediaCleanupRow) -> str:
        if row.encrypted_resource is None:
            raise ValueError("Media cleanup resource is unknown")
        payload = self._cipher.decrypt_json(row.encrypted_resource, context=self._context(row))
        name = payload.get("resource_name")
        if not isinstance(name, str) or not _FILE_NAME.fullmatch(name):
            raise ValueError("Media cleanup resource name is invalid")
        return name

    @staticmethod
    def _public_values(row: MediaCleanupRow) -> dict[str, object]:
        return {
            "id": row.id,
            "provider_id": row.provider_id,
            "state": MediaCleanupState(row.state),
            "known_resource": row.encrypted_resource is not None,
            "attempts": row.attempts,
            "reason": row.reason,
            "lease_until": _utc(row.lease_until) if row.lease_until else None,
            "next_attempt_at": _utc(row.next_attempt_at) if row.next_attempt_at else None,
            "created_at": _utc(row.created_at),
            "updated_at": _utc(row.updated_at),
        }

    @classmethod
    def _record(
        cls, row: MediaCleanupRow, *, resource_name: str | None = None
    ) -> MediaCleanupRecord:
        return MediaCleanupRecord.model_validate(
            {
                **cls._public_values(row),
                "account_fingerprint": row.account_fingerprint,
                "owner_token": row.owner_token,
                "resource_name": resource_name,
            }
        )
