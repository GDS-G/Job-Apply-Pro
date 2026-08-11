from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_apply_pro.domain.challenges import ChallengeEvent, ChallengeSessionSnapshot
from job_apply_pro.storage.models import ChallengeEventRow, ChallengeSessionRow


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class ChallengeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, snapshot: ChallengeSessionSnapshot) -> ChallengeSessionSnapshot:
        row = self._session.get(ChallengeSessionRow, snapshot.id)
        if row is None:
            row = ChallengeSessionRow(
                id=snapshot.id,
                workflow_id=snapshot.workflow_id,
                browser_session_id=snapshot.browser_session_id,
                kind=snapshot.detection.kind.value,
                status=snapshot.status.value,
                snapshot_json=snapshot.model_dump(mode="json"),
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
            )
            self._session.add(row)
        else:
            row.status = snapshot.status.value
            row.snapshot_json = snapshot.model_dump(mode="json")
            row.updated_at = snapshot.updated_at
        self._session.commit()
        return snapshot

    def get(self, session_id: str) -> ChallengeSessionSnapshot | None:
        row = self._session.get(ChallengeSessionRow, session_id)
        return ChallengeSessionSnapshot.model_validate(row.snapshot_json) if row else None

    def list_sessions(self, workflow_id: str | None = None) -> list[ChallengeSessionSnapshot]:
        statement = select(ChallengeSessionRow).order_by(ChallengeSessionRow.updated_at.desc())
        if workflow_id is not None:
            statement = statement.where(ChallengeSessionRow.workflow_id == workflow_id)
        return [
            ChallengeSessionSnapshot.model_validate(row.snapshot_json)
            for row in self._session.scalars(statement).all()
        ]

    def add_event(self, event: ChallengeEvent) -> ChallengeEvent:
        self._session.add(
            ChallengeEventRow(
                id=event.id,
                session_id=event.session_id,
                sequence=event.sequence,
                event_type=event.event_type,
                details_json=event.details,
                occurred_at=event.occurred_at,
            )
        )
        self._session.commit()
        return event

    def list_events(self, session_id: str) -> list[ChallengeEvent]:
        rows = self._session.scalars(
            select(ChallengeEventRow)
            .where(ChallengeEventRow.session_id == session_id)
            .order_by(ChallengeEventRow.sequence)
        ).all()
        return [
            ChallengeEvent(
                id=row.id,
                session_id=row.session_id,
                sequence=row.sequence,
                event_type=row.event_type,
                details=row.details_json,
                occurred_at=_utc(row.occurred_at),
            )
            for row in rows
        ]

    def next_event_sequence(self, session_id: str) -> int:
        latest = self._session.scalar(
            select(func.max(ChallengeEventRow.sequence)).where(
                ChallengeEventRow.session_id == session_id
            )
        )
        return 1 if latest is None else latest + 1
