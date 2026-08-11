from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from job_apply_pro import __version__
from job_apply_pro.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["job-apply-pro-backend"] = "job-apply-pro-backend"
    version: str
    build: str
    environment: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        version=__version__,
        build="Browser Runtime",
        environment=settings.environment,
    )
