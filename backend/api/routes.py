"""API routes with proper request/response models and error handling.

Internal exceptions are logged but never surfaced to clients - every error
response uses the same structured envelope: {"status": "error", "message"}.
"""

import asyncio
import contextvars
import json
import logging
from typing import Any, Literal, Optional

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from config import settings
from models.evidence import InvestigationResult
from observability.tracing import InvestigationTracer
from security import pii
from security import principals as perm
from utils.auth import Principal, require_permission
from utils import log_context
from utils.cancellation import CancellationToken, InvestigationCancelled
from utils.rate_limit import investigate_limiter
from vector_store.search_service import search_incidents
from workflows.rca_graph import NODE_STAGE_IDS, app as rca_graph

logger = logging.getLogger(__name__)

router = APIRouter()

GENERIC_ERROR = "Unable to complete the investigation. Please try again later."


class InvestigateRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=settings.QUESTION_MIN_LENGTH,
        max_length=settings.QUESTION_MAX_LENGTH,
        description="Natural language investigation question",
    )

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question cannot be empty or whitespace")
        return value


class InvestigationResponse(BaseModel):
    """Primary response envelope - structured RCA data with markdown fallback."""

    status: Literal["success", "error"]
    investigation: Optional[InvestigationResult] = None
    report: Optional[str] = None  # markdown fallback (report_markdown)
    message: Optional[str] = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=300)
    limit: int = Field(5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query cannot be empty or whitespace")
        return value


class SearchResponse(BaseModel):
    status: Literal["success", "error"]
    results: list[dict[str, Any]] = []
    message: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    qdrant: bool
    gemini_configured: bool
    llm_provider: str
    llm_model: str
    llm_configured: bool
    data_integrity: dict = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
def health():
    from vector_store.qdrant_setup import collection_exists

    qdrant_ok = False
    try:
        qdrant_ok = collection_exists(settings.QDRANT_COLLECTION)
    except Exception:
        logger.exception("Qdrant health check failed")

    return {
        "status": "healthy",
        "qdrant": qdrant_ok,
        "gemini_configured": bool(settings.GEMINI_API_KEY),
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.llm_model,
        "llm_configured": bool(settings.llm_api_key),
        "data_integrity": _integrity_status(),
    }


def _integrity_status() -> dict:
    try:
        from utils.data_integrity import get_integrity_report, load_provenance

        r = get_integrity_report()
        return {"ok": r.ok, "verified_links": len(r.verified_links),
                "quarantined_links": len(r.quarantined_links),
                "warnings": len(r.by_severity("warning")),
                "provenance": load_provenance()["status"]}
    except Exception:
        logger.exception("Integrity status unavailable")
        return {"ok": False, "error": "integrity check unavailable"}


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest, principal: Principal = Depends(require_permission(perm.INCIDENTS_SEARCH))):
    try:
        # Only the principal's readable services are searched (filter inside Qdrant).
        results = search_incidents(query=pii.redact_text(request.query), limit=request.limit,
                                   services=principal.services)
        return {
            "status": "success",
            "results": [point.payload for point in results],
        }
    except Exception:
        logger.exception("Search failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "message": "Search is currently unavailable."},
        ) from None


def _build_investigation_response(state: dict) -> dict:
    """Shape the final workflow state into the API response."""
    investigation = state.get("investigation")
    if not investigation:
        logger.error("Investigation completed without a result")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": GENERIC_ERROR},
        )
    return {
        "status": investigation.get("status", "success"),
        "investigation": investigation,
        "report": investigation.get("report_markdown"),
        "message": investigation.get("message"),
    }


CANCELLED_STATUS = 499   # client closed the request (nginx convention); nobody receives it


async def _cancel_on_disconnect(request: Request, token: CancellationToken, interval: float = 0.25) -> None:
    """Set the token as soon as the client disconnects, so the workflow stops at its
    next check instead of spending LLM calls on an answer nobody will read."""
    while not token.cancelled:
        if await request.is_disconnected():
            token.cancel("client disconnected")
            return
        await asyncio.sleep(interval)


@router.post("/investigate", response_model=InvestigationResponse)
async def investigate(payload: InvestigateRequest, request: Request,
                      principal: Principal = Depends(require_permission(perm.INVESTIGATIONS_RUN))):
    if not investigate_limiter.check(request, principal.name):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"status": "error", "message": "Too many investigations. Please wait a moment."},
        )

    log_context.set_context(investigation_id=log_context.new_id(), principal=principal.name)
    logger.info("Investigation started (question_length=%d)", len(payload.question))
    tracer = InvestigationTracer(payload.question)
    token = CancellationToken()
    watcher = asyncio.create_task(_cancel_on_disconnect(request, token))
    ctx = contextvars.copy_context()       # request/investigation IDs for the worker thread's logs
    try:
        state = await anyio.to_thread.run_sync(
            ctx.run, lambda: rca_graph.invoke({"question": payload.question, "_tracer": tracer, "_cancel": token,
                                               "_principal": principal}))
    except InvestigationCancelled as exc:
        logger.info("Investigation cancelled at %s (%s)", exc.stage, exc.reason)
        tracer.end(metadata={"status": "cancelled", "stage": exc.stage})
        return JSONResponse(status_code=CANCELLED_STATUS,
                            content={"status": "error", "message": "Investigation cancelled."})
    except Exception:
        logger.exception("Investigation workflow failed")
        tracer.end(metadata={"status": "error"})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": GENERIC_ERROR},
        ) from None
    finally:
        watcher.cancel()

    return _build_investigation_response(state)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/investigate/stream")
def investigate_stream(payload: InvestigateRequest, request: Request,
                       principal: Principal = Depends(require_permission(perm.INVESTIGATIONS_RUN))):
    """SSE endpoint: streams REAL workflow stage completions as they happen
    (driven by LangGraph node updates), followed by the full structured
    result. No stage is reported as complete before its node has finished.
    The workflow runs in a worker thread; if the client disconnects, the
    request's cancellation token is set and the workflow stops at its next check."""
    if not investigate_limiter.check(request, principal.name):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"status": "error", "message": "Too many investigations. Please wait a moment."},
        )
    return StreamingResponse(
        investigation_events(payload.question, principal=principal),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def investigation_events(question: str, token: CancellationToken | None = None,
                               principal: Principal | None = None):
    """SSE events for one investigation. Closing this generator early (client
    disconnect) cancels the investigation."""
    log_context.set_context(investigation_id=log_context.new_id(), principal=principal.name if principal else None)
    question = pii.redact_text(question)      # never echoed or traced with personal data
    logger.info("Streaming investigation started (question_length=%d)", len(question))
    tracer = InvestigationTracer(question)
    token = token or CancellationToken()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def put(item) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:      # event loop closed: the client is gone
            pass

    def worker() -> None:
        try:
            for update in rca_graph.stream({"question": question, "_tracer": tracer, "_cancel": token,
                                            "_principal": principal},
                                           stream_mode="updates"):
                put(("update", update))
            put(("done", None))
        except InvestigationCancelled as exc:
            put(("cancelled", exc))
        except Exception as exc:
            put(("error", exc))

    finished = False
    yield sse("investigation_started", {"question": question})
    loop.run_in_executor(None, contextvars.copy_context().run, worker)
    try:
        final_state: dict = {}
        while not finished:
            kind, item = await queue.get()
            if kind == "update":
                for node_name, node_delta in item.items():
                    stage_id = NODE_STAGE_IDS.get(node_name)
                    if stage_id:
                        yield sse(f"{stage_id}_completed", {"stage": stage_id})
                    if isinstance(node_delta, dict):
                        final_state.update(node_delta)
                continue
            finished = True
            if kind == "done":
                try:
                    result_payload = _build_investigation_response(final_state)
                except Exception:
                    logger.exception("Streaming investigation produced no result")
                    tracer.end(metadata={"status": "error"})
                    yield sse("investigation_error", {"message": GENERIC_ERROR})
                    break
                yield sse("investigation_completed", result_payload)
                tracer.end(metadata={"status": result_payload.get("status")})
            elif kind == "cancelled":
                logger.info("Streaming investigation cancelled at %s (%s)", item.stage, item.reason)
                tracer.end(metadata={"status": "cancelled", "stage": item.stage})
            else:
                logger.error("Streaming investigation failed", exc_info=item)
                tracer.end(metadata={"status": "error"})
                yield sse("investigation_error", {"message": GENERIC_ERROR})
    finally:
        if not finished:          # generator closed early: the client disconnected
            token.cancel("client disconnected")
            logger.info("Client disconnected - streaming investigation cancelled")
            tracer.end(metadata={"status": "cancelled"})
