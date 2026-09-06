"""API routes with proper request/response models and error handling.

Internal exceptions are logged but never surfaced to clients - every error
response uses the same structured envelope: {"status": "error", "message"}.
"""

import json
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from config import settings
from models.evidence import InvestigationResult
from observability.tracing import InvestigationTracer
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
    }


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest):
    try:
        results = search_incidents(query=request.query, limit=request.limit)
        return {
            "status": "success",
            "results": [point.payload for point in results],
        }
    except Exception:
        logger.exception("Search failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "message": "Search is currently unavailable."},
        )


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


@router.post("/investigate", response_model=InvestigationResponse)
def investigate(payload: InvestigateRequest, request: Request):
    if not investigate_limiter.check(request):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"status": "error", "message": "Too many investigations. Please wait a moment."},
        )

    logger.info("Investigation started (question_length=%d)", len(payload.question))
    tracer = InvestigationTracer(payload.question)

    try:
        state = rca_graph.invoke({"question": payload.question, "_tracer": tracer})
    except Exception:
        logger.exception("Investigation workflow failed")
        tracer.end(metadata={"status": "error"})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": GENERIC_ERROR},
        )

    return _build_investigation_response(state)


@router.post("/investigate/stream")
def investigate_stream(payload: InvestigateRequest, request: Request):
    """SSE endpoint: streams REAL workflow stage completions as they happen
    (driven by LangGraph node updates), followed by the full structured
    result. No stage is reported as complete before its node has finished."""
    if not investigate_limiter.check(request):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"status": "error", "message": "Too many investigations. Please wait a moment."},
        )

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

    def event_stream():
        tracer = InvestigationTracer(payload.question)
        yield sse("investigation_started", {"question": payload.question})
        try:
            final_state: dict = {}
            for update in rca_graph.stream(
                {"question": payload.question, "_tracer": tracer},
                stream_mode="updates",
            ):
                for node_name, node_delta in update.items():
                    stage_id = NODE_STAGE_IDS.get(node_name)
                    if stage_id:
                        yield sse(f"{stage_id}_completed", {"stage": stage_id})
                    if isinstance(node_delta, dict):
                        final_state.update(node_delta)
            result_payload = _build_investigation_response(final_state)
            yield sse("investigation_completed", result_payload)
            tracer.end(metadata={
                "status": result_payload.get("status"),
            })
        except Exception:
            logger.exception("Streaming investigation failed")
            tracer.end(metadata={"status": "error"})
            yield sse("investigation_error", {"message": GENERIC_ERROR})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

