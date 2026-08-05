from fastapi import APIRouter
from pydantic import BaseModel

from job_apply_pro.config import get_settings
from job_apply_pro.domain.workflow import WorkflowState

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class Metric(BaseModel):
    label: str
    value: int
    delta: str
    tone: str


class QueueItem(BaseModel):
    id: str
    employer: str
    role: str
    state: WorkflowState
    progress: int
    mode: str


class DashboardSummary(BaseModel):
    metrics: list[Metric]
    queue: list[QueueItem]
    automation_enabled: bool


@router.get("/summary", response_model=DashboardSummary)
def summary() -> DashboardSummary:
    settings = get_settings()
    return DashboardSummary(
        metrics=[
            Metric(label="Qualified roles", value=34, delta="+12 this week", tone="indigo"),
            Metric(label="Ready to review", value=8, delta="3 high priority", tone="amber"),
            Metric(label="Confirmed", value=17, delta="71% completion", tone="emerald"),
            Metric(label="Interviews", value=4, delta="+2 this month", tone="slate"),
        ],
        queue=[
            QueueItem(
                id="wf-1042",
                employer="Northstar Systems",
                role="Senior Platform Engineer",
                state=WorkflowState.FORM_MAPPED,
                progress=64,
                mode="Supervised",
            )
        ],
        automation_enabled=settings.automation_enabled,
    )
