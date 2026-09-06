"""Report content part 6: sections 15-18."""
from generate_report import S, P, bullets, table, Paragraph, W, mm, diag, d_dataflow

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("15. Complete Application Workflow", S["H1"]))
    A(P("<b>Investigation workflow (happy path):</b> User - React UI (InvestigationInput) - services/api.js "
        "investigateStream() - POST /investigate/stream - rate-limiter check - SSE investigation_started - LangGraph: "
        "question_analysis (keywords) - incident_retrieval (Qdrant + threshold) - deployment_correlation "
        "(deployment_id) - log_retrieval (parse/score/cap) - runbook_retrieval (keyword match) - evidence_aggregation "
        "(EvidenceBundle) - evidence_validation (strength + timeline) - rca_generation (Gemini + clamp) - SSE "
        "investigation_completed - React renders RCAReport with EvidencePanel - history saved to localStorage."))
    A(P("Each node completion emits an SSE <stage>_completed event that the LoadingState checklist marks done - "
        "the UI never shows progress the backend has not confirmed."))
    A(P("<b>Failure workflows (implemented):</b>"))
    A(*bullets([
        "Gemini unavailable - retries (3 attempts) then evidence-only fallback result with status 'error' and an explanatory message (verified live in this analysis).",
        "Any retrieval-node failure - recorded in errors/retrieval_errors; workflow continues; the validator adds a note to the result.",
        "Rate limit exceeded - HTTP 429 with a friendly message (tested).",
        "SSE stream failure - investigation_error event with generic message.",
        "Invalid input - HTTP 422 with generic message (tested: missing, short, blank, overlong questions).",
    ]))

    A(Paragraph("16. Complete Data Flow", S["H1"]))
    A(*diag(d_dataflow, 200, "Figure 4 - End-to-end data flow from input to UI, with error paths"))
    A(table(["Stage", "What Happens", "Logging / Errors"], [
        ["Input", "Question arrives as JSON; Pydantic enforces 8-500 chars and rejects blank/whitespace", "422 validation errors logged with request path"],
        ["Processing", "Keyword extraction (regex + stopword list) feeds retrieval; Qdrant cosine scores; log parser scores and sorts by severity/recency", "Per-node info logs with counts; sub-threshold drops logged at debug"],
        ["Business logic", "Evidence aggregated into EvidenceBundle with RetrievalMetadata (counts, min relevance, retrieval_errors); validator computes strength + notes", "Evidence strength logged; notes attached to result"],
        ["External services", "Gemini call with per-attempt logging; Langfuse spans with ms timings (also logged locally so latency is observable without Langfuse)", "Failures logged with full stack internally only"],
        ["Output", "Structured InvestigationResult + markdown fallback; SSE events; React state; localStorage history", "Trace metadata records only question_length - not the question itself - to avoid storing sensitive data"],
        ["Error paths", "Uniform {status, message} envelope; unhandled exceptions caught globally; stack traces never reach the client", "logger.exception at the API boundary"],
    ], [24 * mm, (W - 24 * mm) * 0.62, (W - 24 * mm) * 0.38]))
    return s