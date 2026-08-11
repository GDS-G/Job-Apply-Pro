from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from job_apply_pro import __version__
from job_apply_pro.config import get_settings

router = APIRouter(prefix="/runtime", tags=["runtime"])


class RuntimeStatus(BaseModel):
    status: Literal["ready"] = "ready"
    version: str
    automation_enabled: bool
    authenticated: bool = True
    browser_runtime_available: bool = True
    candidate_knowledge_available: bool = True
    ai_gateway_available: bool = True
    portal_vertical_slice_available: bool = True


@router.get("/status", response_model=RuntimeStatus)
def runtime_status() -> RuntimeStatus:
    return RuntimeStatus(
        version=__version__,
        automation_enabled=get_settings().automation_enabled,
    )
