from fastapi import APIRouter

from job_apply_pro.api.routes import (
    ai,
    browser,
    core,
    dashboard,
    health,
    knowledge,
    portals,
    runtime,
    workbench,
    workflows,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(dashboard.router)
api_router.include_router(workflows.router)
api_router.include_router(core.router)
api_router.include_router(runtime.router)
api_router.include_router(workbench.router)
api_router.include_router(browser.router)
api_router.include_router(knowledge.router)
api_router.include_router(ai.router)
api_router.include_router(portals.router)
