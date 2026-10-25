"""FastAPI application entry point.

Run with:  uvicorn app:app --reload   (from the backend/ directory)
"""

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.actions_routes import router as actions_router
from api.auth_routes import router as auth_router
from api.routes import router
from config import settings
from utils import log_context
from utils.data_store import get_deployments, get_logs, get_runbooks

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the static data cache and validate the vector store on startup.
    logger.info(
        "Starting Enterprise AI Operations Copilot (deployments=%d, logs=%d, runbooks=%d)",
        len(get_deployments()), len(get_logs()), len(get_runbooks()),
    )
    try:
        from vector_store.qdrant_setup import collection_exists, ensure_collection

        if not collection_exists(settings.QDRANT_COLLECTION):
            ensure_collection()
            logger.warning(
                "Qdrant collection '%s' was missing and has been created - "
                "run 'python -m vector_store.load_enterprise_data' to seed it.",
                settings.QDRANT_COLLECTION,
            )
    except Exception:
        logger.exception("Qdrant startup validation failed (continuing anyway)")
    from utils.auth import startup_check

    startup_check()
    # Single-process limits (RELIABILITY_AUDIT D16): embedded Qdrant locks its
    # storage folder to one process, and the rate limiter counts in memory.
    workers = os.getenv("WEB_CONCURRENCY", "1")
    if workers.isdigit() and int(workers) > 1:
        logger.error("WEB_CONCURRENCY=%s: this deployment supports ONE worker process (embedded Qdrant "
                     "storage lock, in-memory rate limiter). Use a Qdrant server and a shared rate-limit "
                     "store before running several workers.", workers)
    yield
    logger.info("Shutting down Enterprise AI Operations Copilot")


app = FastAPI(
    title="Enterprise AI Operations Copilot",
    description="RAG-based Root Cause Analysis copilot for enterprise operations.",
    version="1.1.0",
    lifespan=lifespan,
)

# CORS is configurable via the CORS_ORIGINS environment variable
# (comma-separated). Never use a wildcard in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-CSRF-Token"],
)

app.include_router(router)
app.include_router(auth_router)
app.include_router(actions_router)


class RequestContextMiddleware:
    """Request ID on every log line and response (X-Request-ID); one access log
    line per request with method, path, status and duration - no query string,
    body or headers.

    Pure ASGI on purpose: Starlette's BaseHTTPMiddleware (@app.middleware) wraps
    ``receive``, which hid client disconnects from ``request.is_disconnected()``
    and so stopped /investigate from cancelling (found in a real disconnect test)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        request_id = log_context.request_id_from(headers.get("x-request-id"))
        tokens = log_context.set_context(request_id=request_id)
        start = time.perf_counter()
        status_code = 500

        async def send_with_id(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message = dict(message, headers=list(message.get("headers", []))
                               + [(b"x-request-id", request_id.encode("latin-1"))])
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            method, path = scope.get("method", ""), scope.get("path", "")
            logger.info("%s %s -> %d", method, path, status_code,
                        extra={"method": method, "path": path, "status_code": status_code,
                               "duration_ms": round((time.perf_counter() - start) * 1000)})
            log_context.reset_context(tokens)


app.add_middleware(RequestContextMiddleware)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Normalise all HTTP errors into the same user-safe envelope.
    detail = exc.detail
    if isinstance(detail, dict) and "message" in detail:
        content = {"status": "error", "message": detail["message"]}
    elif isinstance(detail, str):
        content = {"status": "error", "message": detail}
    else:
        logger.warning("Unhandled HTTPException detail on %s", request.url.path)
        content = {
            "status": "error",
            "message": "An unexpected error occurred. Please try again later.",
        }
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Only the error type and location are logged - never the submitted input
    # (pydantic includes it in exc.errors(), and it may contain personal data).
    logger.warning("Validation error on %s: %s", request.url.path,
                   [(e.get("type"), ".".join(str(x) for x in e.get("loc", ()))) for e in exc.errors()])
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "message": "Invalid request. Please check your input and try again.",
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "An unexpected error occurred. Please try again later.",
        },
    )
