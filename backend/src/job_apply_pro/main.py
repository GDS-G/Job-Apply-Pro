import secrets
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from job_apply_pro import __version__
from job_apply_pro.api.router import api_router
from job_apply_pro.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Job Apply Pro Local API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
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
        return await call_next(request)

    application.include_router(api_router)
    return application


app = create_app()
