"""FastAPI application entry point.

Run with:  uvicorn app:app --reload   (from the backend/ directory)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import router
from config import settings
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
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(router)


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
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("Validation error on %s: %s", request.url.path, exc.errors())
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
