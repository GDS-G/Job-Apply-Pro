from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from job_apply_pro import __version__
from job_apply_pro.api.router import api_router


def create_app() -> FastAPI:
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
        allow_headers=["Content-Type"],
    )
    application.include_router(api_router)
    return application


app = create_app()
