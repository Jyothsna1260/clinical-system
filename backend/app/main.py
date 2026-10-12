"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.errors import error_body, install_error_handlers
from app.api.routes import auth, eligibility, health, patients, trials
from app.config import get_settings
from app.logging_config import configure_logging
from app.services.analysis import fail_interrupted_runs
from app.state import get_run_state
from app.storage import get_store, reset_store

settings = get_settings()
configure_logging(settings.log_level)
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
    interrupted = fail_interrupted_runs(store, settings.stale_run_minutes)
    if interrupted:
        log.warning("marked %d interrupted analysis run(s) as failed", interrupted)
    where = store.root.resolve() if store.kind == "file" else "DATABASE_URL"
    log.info("%s store ready at %s; workflow state: %s (env=%s)",
             store.kind, where, get_run_state().kind, settings.app_env)
    yield
    reset_store()  # closes the PostgreSQL connection pool so shutdown is prompt


app = FastAPI(
    title="Clinical Trial Eligibility & Exclusion Contradiction System",
    version=__version__,
    description="Agentic clinical decision support. Supports, and does not replace, qualified clinical review.",
    lifespan=lifespan,
    # Interactive docs stay on in production: the API is the product's public contract.
)

MULTIPART_OVERHEAD_BYTES = 1024 * 1024  # form boundaries and the title field


@app.middleware("http")
async def reject_oversized_uploads(request: Request, call_next):
    """Refuse an oversized protocol upload from its Content-Length, before the body is received.

    The endpoint still checks the actual file size, so a missing or false header changes nothing.
    """
    if request.method == "POST" and request.url.path == "/api/trials/upload":
        length = request.headers.get("content-length", "")
        limit = settings.max_upload_mb * 1024 * 1024 + MULTIPART_OVERHEAD_BYTES
        if length.isdigit() and int(length) > limit:
            return JSONResponse(status_code=413, content=error_body(
                "FILE_TOO_LARGE", f"Protocol PDF must be at most {settings.max_upload_mb} MB."))
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if settings.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


# Added last so it is the outermost layer: every response, including early 413s, carries CORS headers
# and the browser can read the error.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.frontend_origin_regex or None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

install_error_handlers(app)
for module in (health, auth, trials, patients, eligibility):
    app.include_router(module.router)
