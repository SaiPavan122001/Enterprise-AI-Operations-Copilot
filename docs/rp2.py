"""Report content part 2: sections 5-7."""
from generate_report import S, P, bullets, table, Paragraph, Spacer, W, mm, diag, d_arch, d_pipeline

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("5. Features & Functionalities", S["H1"]))
    for name, what, how in [
        ("RCA Investigation Pipeline",
         "Turns a question into a structured RCA (summary, impact, root cause, confidence, contributing factors, remediation, preventive actions, timeline, evidence bundle, validation verdict).",
         "LangGraph StateGraph with 8 sequential nodes; each node wraps an agent and records errors defensively (workflows/rca_graph.py)."),
        ("Semantic Incident Search (RAG)",
         "Finds incidents semantically similar to the question.",
         "SentenceTransformer embeds the query; Qdrant cosine top-k with payload indexes; threshold filtering (vector_store/, agents/incident_agent.py)."),
        ("Deployment Correlation",
         "Links matched incidents to the exact deployments that may have caused them.",
         "Explicit deployment_id join; service-name fallback only when no ID matches (agents/deployment_agent.py)."),
        ("Log Evidence Extraction",
         "Surfaces relevant ERROR/WARN lines without dumping raw logs into the prompt.",
         "Regex parser for 'timestamp service LEVEL message' lines; relevance scoring; cap of 40 lines (agents/log_agent.py)."),
        ("Runbook Guidance",
         "Provides operational remediation context distinct from observed evidence.",
         "Keyword-scored selection over 5 curated markdown runbooks, capped at 4000 chars (agents/runbook_agent.py)."),
        ("Evidence Validation & Confidence Gating",
         "Computes evidence strength and clamps the LLM's confidence claim.",
         "Deterministic heuristic using incident relevance (0.45 threshold for HIGH) and corroboration counts (rca_graph.py, _final_confidence)."),
        ("Grounded LLM RCA Generation",
         "Generates the human-readable RCA report.",
         "Structured prompt with explicit anti-hallucination instructions; markdown parsed into structured sections; retries; evidence-only fallback (agents/gemini_rca_agent.py)."),
        ("Real-Time Progress Streaming",
         "Users see each pipeline stage complete as it happens.",
         "POST /investigate/stream emits SSE events driven by LangGraph stream_mode='updates'; LoadingState marks stages done only on backend confirmation."),
        ("Evidence Inspection UI",
         "Every RCA is accompanied by its raw evidence.",
         "EvidencePanel accordions: incidents (with relevance labels), deployments, copyable log lines, runbook card, AI-cited facts."),
        ("History & Feedback",
         "Recent investigations are searchable and restorable; thumbs-up/down feedback with reason capture.",
         "localStorage keys copilot-history (max 20) / copilot-feedback (max 100); Sidebar search; Feedback component."),
        ("Health Indicator",
         "Shows backend connectivity at a glance.",
         "Header polls GET /health every 30 s; status pill shows Systems operational / Backend offline."),
        ("Theming",
         "Dark (default) and light themes.",
         "document.documentElement.dataset.theme toggle persisted in localStorage (copilot-theme)."),
    ]:
        A(Paragraph(name, S["H3"]))
        A(P("<b>What:</b> " + what))
        A(P("<b>How:</b> " + how))
    A(Paragraph("5.2 Partially Implemented / Recommended", S["H2"]))
    A(*bullets([
        "<b>MCP tool server (partially implemented):</b> backend/mcp_server/server.py exposes four real tools (search_incidents_tool, get_deployment, search_logs, get_runbook) via FastMCP, but it is an isolated optional integration - no agent currently consumes it and it is not wired into the main API.",
        "<b>Langfuse tracing (implemented, optional):</b> one trace per investigation with per-stage spans and stage timings; fully fail-soft when unconfigured.",
        "<b>Not implemented (recommended):</b> authentication/authorization, server-side persistence, Docker/CI-CD, automated E2E tests, live telemetry ingestion.",
    ]))
    A(Paragraph("6. Technology Stack", S["H1"]))
    A(table(["Technology", "Version", "Purpose", "Where Used"], [
        ["Python", "3.12 (3.12.10 verified)", "Backend language", "backend/"],
        ["FastAPI", "0.115.6", "HTTP API framework, CORS, validation, SSE", "backend/app.py, api/routes.py"],
        ["Pydantic", "2.10.4", "Request/response models and evidence contracts", "api/routes.py, models/evidence.py"],
        ["uvicorn[standard]", "0.34.0", "ASGI server", "backend launch"],
        ["LangGraph", "0.2.60", "Investigation workflow orchestration", "workflows/rca_graph.py"],
        ["google-genai", "0.6.0", "Gemini LLM client", "agents/gemini_rca_agent.py"],
        ["Gemini 2.5 Flash", "gemini-2.5-flash (default)", "RCA generation LLM (external API)", "configurable via GEMINI_MODEL"],
        ["SentenceTransformers", "3.3.1", "Embeddings: BAAI/bge-small-en-v1.5 (384-dim)", "vector_store/search_service.py, scripts/seed.py"],
        ["Qdrant client", "1.12.1", "Vector database (embedded local mode)", "vector_store/"],
        ["Langfuse SDK", ">=3.0.0,<4", "Optional LLM observability (traces/spans)", "observability/"],
        ["python-dotenv", "1.0.1", "Environment configuration", "config.py, observability/langfuse_client.py"],
        ["pytest", "8.3.4", "Backend testing", "backend/tests/"],
        ["httpx", "0.28.1", "Test client transport", "tests via FastAPI TestClient"],
        ["FastMCP (mcp)", "package 'mcp'", "Optional MCP tool server", "backend/mcp_server/server.py"],
        ["React", "^19.2.6", "Frontend UI framework", "frontend/src/"],
        ["Vite", "^6.0.5 (6.4.3 verified)", "Dev server and production build", "frontend/vite.config.js"],
        ["react-markdown", "^9.0.1", "Renders markdown RCA sections", "RCAReport.jsx, InvestigationMessage.jsx"],
        ["ESLint", "^9.17.0", "Frontend linting (npm run lint)", "eslint.config.js"],
        ["JavaScript (ESM)", "ES2022+ (Node 24 verified)", "Frontend language", "frontend/src/"],
        ["CSS (plain)", "-", "Theming and responsive layout", "App.css, index.css"],
    ], [34 * mm, 30 * mm, W - 64 * mm - 42 * mm, 42 * mm]))
    A(P("<b>Not identified in the current implementation:</b> relational/document databases (PostgreSQL, Supabase, "
        "MongoDB), authentication libraries (JWT/OAuth), Docker, CI/CD tooling, cloud SDKs, E2E/UI testing "
        "frameworks (Playwright, Cypress), and monitoring infrastructure."))

    A(Paragraph("7. System Architecture", S["H1"]))
    A(P("The application follows a classic two-tier client/server design with an internal multi-agent pipeline. "
        "The React SPA communicates only with the FastAPI backend; all retrieval, correlation, validation and "
        "LLM work happens server-side behind a single API surface."))
    A(*diag(d_arch, 300, "Figure 1 - System architecture: frontend, API, LangGraph pipeline and backing stores"))
    A(Paragraph("7.1 Architecture Explanation", S["H2"]))
    A(*bullets([
        "<b>Client tier:</b> React 19 SPA (Vite). All backend access goes through services/api.js using VITE_API_URL - no hardcoded URLs in components. Streaming progress arrives via SSE; history/theme live in localStorage.",
        "<b>API tier:</b> FastAPI exposes /health, /search, /investigate and /investigate/stream. Pydantic models validate input; a per-IP rate limiter guards the expensive endpoints; all errors use a uniform {status, message} envelope.",
        "<b>Workflow tier:</b> a compiled LangGraph StateGraph orchestrates 8 nodes. Each node catches its own exceptions and appends to state['errors'], so partial evidence still produces a report.",
        "<b>Data tier:</b> an embedded Qdrant instance persists incident vectors on disk (backend/qdrant_data); deployments/logs/runbooks are static files cached in memory via lru_cache.",
        "<b>External services:</b> Google Gemini (LLM) and Langfuse Cloud (optional tracing) are the only external dependencies; both calls fail soft or fall back.",
        "<b>Deployment shape today:</b> everything runs on one machine - uvicorn process, embedded Qdrant, Vite dev server (or built dist/).",
    ]))
    A(*diag(d_pipeline, 110, "Figure 2 - LangGraph RCA workflow node sequence (start to END)"))
    return s