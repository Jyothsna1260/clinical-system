"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import install_error_handlers
from app.api.routes import auth, eligibility, health, patients, trials
from app.config import get_settings
from app.state import get_run_state
from app.storage import get_store

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
log = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    for directory in (settings.data_dir, settings.uploads_dir, settings.index_dir):
        directory.mkdir(parents=True, exist_ok=True)
    store = get_store()
    where = store.root.resolve() if store.kind == "file" else "DATABASE_URL"
    log.info("%s store ready at %s; workflow state: %s (env=%s)",
             store.kind, where, get_run_state().kind, settings.app_env)
    yield


app = FastAPI(
    title="Clinical Trial Eligibility & Exclusion Contradiction System",
    version=__version__,
    description="Agentic clinical decision support. Supports, and does not replace, qualified clinical review.",
    lifespan=lifespan,
    # Interactive docs stay on in production: the API is the product's public contract.
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.frontend_origin_regex or None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if settings.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


install_error_handlers(app)
for module in (health, auth, trials, patients, eligibility):
    app.include_router(module.router)
