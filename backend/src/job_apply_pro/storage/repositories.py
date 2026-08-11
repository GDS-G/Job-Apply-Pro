from datetime import UTC

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_apply_pro.domain.workflow import VerificationResult, WorkflowEvent, WorkflowState
from job_apply_pro.storage.models import WorkflowEventRow


class WorkflowEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def next_sequence(self, workflow_id: str) -> int:
        statement = select(func.max(WorkflowEventRow.sequence)).where(
            WorkflowEventRow.workflow_id == workflow_id
        )
        latest = self._session.scalar(statement)
        return 1 if latest is None else latest + 1

    def add(self, event: WorkflowEvent) -> WorkflowEvent:
        self._session.add(
            WorkflowEventRow(
                id=event.id,
                workflow_id=event.workflow_id,
                sequence=event.sequence,
                prior_state=event.prior_state.value,
                next_state=event.next_state.value,
                actor=event.actor,
                cause=event.cause,
                verification=event.verification.value,
                retry_count=event.retry_count,
                occurred_at=event.occurred_at,
            )
        )
        self._session.commit()
        return event

    def list_for_workflow(self, workflow_id: str) -> list[WorkflowEvent]:
        statement = (
            select(WorkflowEventRow)
            .where(WorkflowEventRow.workflow_id == workflow_id)
            .order_by(WorkflowEventRow.sequence)
        )
        rows = self._session.scalars(statement).all()
        return [
            WorkflowEvent(
                id=row.id,
                workflow_id=row.workflow_id,
                sequence=row.sequence,
                prior_state=WorkflowState(row.prior_state),
                next_state=WorkflowState(row.next_state),
                actor=row.actor,
                cause=row.cause,
                verification=VerificationResult(row.verification),
                retry_count=row.retry_count,
                occurred_at=(
                    row.occurred_at
                    if row.occurred_at.tzinfo is not None
                    else row.occurred_at.replace(tzinfo=UTC)
                ),
            )
            for row in rows
        ]
