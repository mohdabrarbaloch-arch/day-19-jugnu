"""Jugnu — application entrypoint.

Wires routers, security headers, CORS, error handling and the static UI.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.db import init_db
from app.routers import auth, public, search, threads

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("jugnu")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    logger.info(
        "Jugnu starting | env=%s providers=%s answer=%s",
        settings.environment,
        ",".join(settings.provider_chain),
        settings.answer_provider,
    )
    if settings.is_production and settings.secret_key.startswith("dev-"):
        logger.warning("SECRET_KEY looks like a development default — set a real one.")
    yield
    logger.info("Jugnu shutting down")


app = FastAPI(
    title="Jugnu API",
    version="1.0.0",
    description=(
        "A conversational search engine. Ask a question, get an answer where "
        "every sentence is traceable to a source you can open."
    ),
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# --------------------------------------------------------------------------
# middleware
# --------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Security headers, applied to every response including errors."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'",
    )
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# --------------------------------------------------------------------------
# error handling — every error is JSON with a `detail` string
# --------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


def _safe_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    """Pydantic v2 puts the original exception object in `ctx`, which is not
    JSON-serialisable. Serialising it raises TypeError inside the error handler
    and turns a clean 422 into a 500, so we flatten to plain strings."""
    out: list[dict[str, str]] = []
    for err in exc.errors()[:5]:
        out.append(
            {
                "loc": ".".join(str(p) for p in err.get("loc", [])),
                "msg": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
        )
    return out


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    # Flatten pydantic's structure into something a UI can show directly.
    errors = _safe_errors(exc)
    first = errors[0] if errors else {}
    field = first.get("loc", "").replace("body.", "")
    message = first.get("msg", "Invalid request")
    detail = f"{field}: {message}" if field else message
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": detail, "errors": errors},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    logger.exception("unhandled error: %s", exc)
    # Never leak a stack trace to the client.
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Something went wrong on our side. Please try again."},
    )


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(search.router)
app.include_router(threads.router)
app.include_router(public.router)

static_dir = settings.static_dir
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", include_in_schema=False)
async def index():
    index_file = static_dir / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return JSONResponse({"detail": "UI not built", "docs": "/api/docs"})


@app.get("/s/{slug}", include_in_schema=False)
async def shared_thread_page(slug: str):
    """Serve the SPA for a shared thread; the client reads the slug from the URL."""
    index_file = static_dir / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return JSONResponse({"detail": "UI not built"}, status_code=404)
