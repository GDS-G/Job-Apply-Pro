import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from job_apply_pro import __version__
from job_apply_pro.api.router import api_router
from job_apply_pro.api.routes.browser import shutdown_browser_worker
from job_apply_pro.config import get_settings
from job_apply_pro.storage.database import SessionFactory
from job_apply_pro.storage.models import ErrorRecordRow


def _record_server_error(request: Request, classification: str, status_code: int) -> None:
    route = request.scope.get("route")
    route_template = getattr(route, "path", "unmatched")
    try:
        with SessionFactory() as session:
            session.add(
                ErrorRecordRow(
                    id=str(uuid4()),
                    workflow_id=None,
                    classification=classification,
                    component="api",
                    action=request.method,
                    sanitized_context_json={
                        "route_template": route_template,
                        "status_code": status_code,
                    },
                    retry_count=0,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
    except Exception:
        # Telemetry must never hide or replace the original application failure.
        return


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        yield
        shutdown_browser_worker()

    application = FastAPI(
        title="Job Apply Pro Local API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Job-Apply-Pro-Token"],
    )

    @application.middleware("http")
    async def authenticate_local_api(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        configured_token = settings.api_token
        is_protected = request.url.path.startswith("/api/v1/") and request.url.path not in {
            "/api/v1/health"
        }
        if configured_token is not None and is_protected:
            provided_token = request.headers.get("X-Job-Apply-Pro-Token", "")
            if not secrets.compare_digest(provided_token, configured_token.get_secret_value()):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Local API authentication failed"},
                )
        try:
            response = await call_next(request)
        except Exception:
            _record_server_error(request, "UNHANDLED_EXCEPTION", 500)
            raise
        if response.status_code >= 500:
            _record_server_error(request, "HTTP_SERVER_ERROR", response.status_code)
        return response

    application.include_router(api_router)
    return application


app = create_app()
