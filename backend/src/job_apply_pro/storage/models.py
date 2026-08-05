from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from job_apply_pro.storage.database import Base


class WorkflowEventRow(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_workflow_event_sequence"),
        Index("ix_workflow_events_workflow_occurred", "workflow_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(100), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    prior_state: Mapped[str] = mapped_column(String(40))
    next_state: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(100))
    cause: Mapped[str] = mapped_column(Text)
    verification: Mapped[str] = mapped_column(String(20))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
