from fastapi import APIRouter

from job_apply_pro.api.routes import core, dashboard, health, workflows

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(dashboard.router)
api_router.include_router(workflows.router)
api_router.include_router(core.router)
