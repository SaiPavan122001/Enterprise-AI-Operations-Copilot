"""Report content part 3: sections 8-10."""
from generate_report import S, P, bullets, table, Paragraph, W, mm

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("8. Detailed Component Architecture", S["H1"]))
    A(table(["Component", "Responsibility", "Inputs", "Outputs", "Key Interactions / Files"], [
        ["FastAPI app", "App lifecycle, CORS, error handlers, startup validation of Qdrant collection", "HTTP requests", "JSON / SSE responses", "app.py, config.py, vector_store/qdrant_setup.py"],
        ["Routes", "Request validation, rate limiting, tracing, response envelope", "question / query JSON", "InvestigationResponse, SearchResponse, HealthResponse, SSE events", "api/routes.py, models/evidence.py, utils/rate_limit.py"],
        ["LangGraph workflow", "Orchestrate the 8-node investigation; defensive error capture; timeline; validation", "RCAState(question)", "RCAState(investigation)", "workflows/rca_graph.py"],
        ["Incident agent", "Semantic retrieval + relevance threshold filtering", "question, limit=5", "list[IncidentEvidence] + scores", "vector_store/search_service.py"],
        ["Deployment agent", "deployment_id correlation with service fallback", "list[IncidentEvidence]", "list[DeploymentEvidence]", "utils/data_store.get_deployments"],
        ["Log agent", "Parse, score, prioritise and cap log evidence", "incidents, keywords, deployments", "list[LogEvidence] (max 40)", "utils/data_store.get_logs"],
        ["Runbook agent", "Best-matching operational runbook", "question, incidents", "RunbookEvidence | None", "data/runbooks/*.md"],
        ["Evidence validator", "Strength heuristic + notes + timeline (real timestamps only)", "EvidenceBundle", "EvidenceValidation, list[TimelineEvent]", "workflows/rca_graph.py"],
        ["Gemini RCA agent", "Grounded prompt, retries, markdown parse, confidence clamping, fallback", "EvidenceBundle, EvidenceValidation, timeline", "InvestigationResult (never raises)", "google-genai client, observability.tracing"],
        ["Qdrant layer", "Collection lifecycle, payload indexes, vector search", "query vector, optional filters", "scored points", "vector_store/qdrant_setup.py, search_service.py"],
        ["Data store", "Cached loading of static enterprise data", "data/ files", "deployments list, log lines, runbooks dict", "utils/data_store.py (lru_cache)"],
        ["Tracer", "One Langfuse trace per investigation; stage spans + timings; noop when unconfigured", "question length", "trace metadata, ms timings", "observability/tracing.py, langfuse_client.py"],
        ["Rate limiter", "Sliding-window per-IP limiting of /investigate", "Request", "bool allow/deny", "utils/rate_limit.py"],
        ["React App", "Layout, message state, SSE handling, history, theme", "user question", "messages, history, UI", "App.jsx, components/*"],
        ["api.js client", "Typed fetch wrappers with timeouts and user-safe errors", "question / query", "investigation payload / events / health", "frontend/src/services/api.js"],
    ], [24 * mm, 34 * mm, 26 * mm, 32 * mm, W - 116 * mm]))
    A(Paragraph("9. Frontend Architecture", S["H1"]))
    A(P("The frontend is a single-page React application with no router - the whole product is one screen "
        "(chat-style investigations) plus a collapsible sidebar. State is local React state (useState/useCallback) "
        "plus localStorage; no state-management library is used, which is appropriate for the app's size."))
    A(table(["Aspect", "Implementation"], [
        ["Entry", "main.jsx - App.jsx (app-shell: Sidebar + main area)"],
        ["Screens", "Welcome screen with 4 example investigation cards; chat window with user/assistant messages; loading stage list; empty and error states"],
        ["Components", "Header (health pill, theme, sidebar toggle), Sidebar (history search/restoration), InvestigationInput (textarea, char limit, Enter/Shift+Enter), InvestigationMessage, RCAReport (structured sections), EvidencePanel (accordions), Timeline, LoadingState (stage checklist), Feedback"],
        ["Reusable pieces", "SectionCard / ConfidenceBadge / ListSection (RCAReport.jsx); Accordion (EvidencePanel.jsx)"],
        ["State management", "Local useState: messages[], loading, completedStages (Set of backend-confirmed stage ids), history, theme; loadingRef guards concurrent submissions"],
        ["Routing", "None - single view; sidebar navigation and New Investigation reset messages"],
        ["API communication", "services/api.js: investigate() (POST, 180 s timeout), investigateStream() (SSE parser over fetch ReadableStream), checkHealth() (5 s timeout, 30 s poll)"],
        ["Forms & validation", "Question limited to 500 chars (mirrors backend), non-blank submit guard, live counter with limit-hit styling"],
        ["Auth UI", "None - not identified in the current implementation"],
        ["Error handling", "userSafeError() surfaces backend 'message' only; timeout/network errors map to friendly text; error card with role=status notice banner"],
        ["Responsive design", "Sidebar overlay with backdrop on small screens; CSS variables theme both dark/light"],
        ["UX details", "Smooth auto-scroll to latest message; copy-to-clipboard for log evidence; aria-expanded accordions; honest loading copy (no fake checkmarks)"],
    ], [30 * mm, W - 30 * mm]))

    A(Paragraph("10. Backend Architecture", S["H1"]))
    A(table(["Aspect", "Implementation"], [
        ["Framework", "FastAPI 0.115.6 served by uvicorn (single process)"],
        ["Structure", "app.py (app + lifespan + handlers) - api/routes.py (4 endpoints) - workflows/ and agents/ (business logic) - vector_store/ + utils/ (data)"],
        ["Routes", "GET /health, POST /search, POST /investigate, POST /investigate/stream (SSE StreamingResponse with no-cache and X-Accel-Buffering: no)"],
        ["Middleware", "CORS with configurable allow-list (CORS_ORIGINS); GET/POST methods only; Authorization/Content-Type headers only"],
        ["Validation", "Pydantic field constraints + custom validators (blank rejection); mirrored QUESTION_MIN/MAX_LENGTH limits"],
        ["Business logic", "LangGraph nodes calling agent functions; all cross-stage data passes through Pydantic models (models/evidence.py) - no ad-hoc dicts"],
        ["Authentication", "None - endpoints are public on the local network (README requires auth before public deployment)"],
        ["Authorization", "None - not identified in the current implementation"],
        ["Error handling", "Dedicated handlers for HTTPException, RequestValidationError and generic Exception; internals logged, users get generic messages"],
        ["Data interaction", "Qdrant embedded client (path-based); lru_cache for static files; refresh_data_cache() provided for maintenance"],
        ["External integrations", "Gemini generate_content (timeout GEMINI_TIMEOUT_MS, retries GEMINI_MAX_RETRIES); Langfuse traces (fail-soft)"],
        ["Startup (lifespan)", "Warms data cache, logs counts, creates Qdrant collection if missing (warns to run the seed script)"],
    ], [30 * mm, W - 30 * mm]))
    return s