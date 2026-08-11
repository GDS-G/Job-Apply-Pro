from fastapi import APIRouter

from job_apply_pro.api.routes import browser, core, dashboard, health, runtime, workbench, workflows

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(dashboard.router)
api_router.include_router(workflows.router)
api_router.include_router(core.router)
api_router.include_router(runtime.router)
api_router.include_router(workbench.router)
api_router.include_router(browser.router)
