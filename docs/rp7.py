"""Report content part 7: sections 17-18."""
from generate_report import S, P, bullets, table, Paragraph, W, mm

CODE_TREE = (
    "Enterprise-ai-operations-copilot/<br/>"
    "|-- README.md                    Overview, architecture, setup, API, production notes<br/>"
    "|-- .env.example / .gitignore    Configuration template and VCS exclusions<br/>"
    "|-- docs/                        Screenshots; report generator<br/>"
    "|-- backend/<br/>"
    "|   |-- app.py                  FastAPI entry, CORS, error handlers, lifespan<br/>"
    "|   |-- config.py               Environment-driven settings (single source of truth)<br/>"
    "|   |-- requirements.txt        Pinned dependencies<br/>"
    "|   |-- api/routes.py           Endpoints + Pydantic request/response models<br/>"
    "|   |-- agents/                 incident, deployment, log, runbook, gemini_rca<br/>"
    "|   |-- workflows/rca_graph.py  LangGraph 8-node investigation graph<br/>"
    "|   |-- models/evidence.py      Pydantic evidence contracts (cross-stage types)<br/>"
    "|   |-- vector_store/           Qdrant client/setup/search + seed wrapper<br/>"
    "|   |-- utils/                  data_store (lru_cache), rate_limit<br/>"
    "|   |-- observability/          Langfuse client + tracer (fail-soft)<br/>"
    "|   |-- mcp_server/server.py    Optional FastMCP tool server (4 tools)<br/>"
    "|   |-- scripts/seed.py         Canonical Qdrant seeding command<br/>"
    "|   |-- data/                   incidents, deployments, logs, runbooks<br/>"
    "|   |-- tests/                  conftest.py, test_agents.py, test_api.py<br/>"
    "|   -- qdrant_data/            Embedded Qdrant persistence (generated)<br/>"
    "-- frontend/<br/>"
    "    |-- package.json / vite.config.js / eslint.config.js<br/>"
    "    |-- .env.example            VITE_API_URL<br/>"
    "    -- src/<br/>"
    "        |-- App.jsx            Layout, state, SSE flow, history, theme<br/>"
    "        |-- services/api.js    Backend client (investigate, stream, health)<br/>"
    "        -- components/         Header, Sidebar, InvestigationInput, InvestigationMessage,<br/>"
    "                               RCAReport, EvidencePanel, Timeline, LoadingState, Feedback")

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("17. Project Folder Structure", S["H1"]))
    A(Paragraph(CODE_TREE, S["Code"]))
    A(P("Key responsibilities: <b>config.py</b> centralises every environment variable so no module reads os.environ "
        "directly; <b>models/evidence.py</b> is the contract layer that makes stages independently testable; "
        "<b>scripts/seed.py</b> is the single canonical way to populate the vector store (an older entry point, "
        "vector_store/load_enterprise_data.py, is kept as a thin deprecated wrapper)."))
    A(Paragraph("18. Module & Implementation Details", S["H1"]))
    A(table(["Module", "Main Logic", "Dependencies", "I/O"], [
        ["config.py", "Settings reading env once (Gemini, Langfuse, Qdrant, CORS, rate limits, validation limits, MIN_RELEVANCE_SCORE, LOG_LEVEL); root logging; warns when GEMINI_API_KEY missing", "python-dotenv", "settings object"],
        ["api/routes.py", "4 endpoints; Pydantic models with field_validator blank checks; rate limiter check; tracer per investigation; graph.invoke / graph.stream(updates) - SSE per node; response envelope builder", "FastAPI, LangGraph app", "HTTP JSON / SSE"],
        ["workflows/rca_graph.py", "TypedDict RCAState; 8 nodes each with try/except/finally tracing; _build_timeline from real timestamps (cap 15); strength heuristic; compiled StateGraph; NODE_STAGE_IDS for SSE", "agents, models", "final state"],
        ["agents/incident_agent.py", "search_incidents + threshold filter (0.30); returns incidents + scores", "vector_store, config", "list[IncidentEvidence]"],
        ["agents/deployment_agent.py", "deployment_id exact join; service fallback only if no ID matched (cap 10)", "utils.data_store", "list[DeploymentEvidence]"],
        ["agents/log_agent.py", "Regex LOG_LINE_RE parse; LEVEL_PRIORITY + ERROR_TERMS scoring; sort by (-relevance, timestamp); cap 40", "utils.data_store", "list[LogEvidence]"],
        ["agents/runbook_agent.py", "RUNBOOK_KEYWORDS domain map; substring/token scoring; best match wins; content capped 4000 chars", "utils.data_store", "RunbookEvidence | None"],
        ["agents/gemini_rca_agent.py", "RCA_PROMPT template; formatting helpers with caps; 3 attempts; _build_result parses markdown sections; _final_confidence clamp; _fallback_result evidence-only", "google-genai, config, tracing", "InvestigationResult (never raises)"],
        ["vector_store/*", "qdrant_client (path client); qdrant_setup (ensure_collection, 384-dim cosine, 3 payload indexes); search_service (encode + query_points + filters)", "qdrant-client, sentence-transformers", "scored points"],
        ["scripts/seed.py", "validate_data (required fields) - ensure_collection - embed - upsert (uuid5 ids) - count verification - exit codes", "qdrant, sentence-transformers", "seeded collection"],
        ["utils/rate_limit.py", "Sliding-window per-IP limiter using time.monotonic; module-level instance from settings", "config", "allow/deny"],
        ["observability/*", "Defensive Langfuse init (None on failure); noop-safe spans; stage duration in ms", "langfuse SDK", "traces"],
        ["frontend/src/App.jsx", "Message array state; runInvestigation prefers stream with fallback to non-streaming; pushHistory with quota fallback; theme + history persistence", "components, api.js", "UI"],
        ["frontend/src/services/api.js", "fetchWithTimeout (AbortController); SSE parser over ReadableStream; STAGES mirroring NODE_STAGE_IDS; checkHealth", "fetch API", "promises/events"],
    ], [30 * mm, (W - 30 * mm) * 0.52, (W - 30 * mm) * 0.24, (W - 30 * mm) * 0.24]))
    return s