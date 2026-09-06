"""Report content part 1: sections 1-4."""
from generate_report import S, P, bullets, table, Paragraph, W, mm

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("1. Executive Summary", S["H1"]))
    A(P("The <b>Enterprise AI Operations Copilot</b> is an AI-powered application that performs automated "
        "Root Cause Analysis (RCA) of enterprise incidents. A user asks a natural-language question such as "
        "<i>\"Why is payroll failing?\"</i> and the system retrieves relevant incidents (semantic vector search), "
        "correlates them with deployments, prioritises relevant log entries, retrieves matching operational "
        "runbooks, validates the aggregated evidence, and generates a grounded, structured RCA report using "
        "Google Gemini 2.5 Flash."))
    A(P("The system is deliberately engineered to be <b>honest and grounded</b>: the LLM never reports a "
        "confidence higher than the evidence allows, timelines are built only from real timestamps, runbook "
        "content is presented as guidance (never as observed evidence), and if the LLM is unavailable the API "
        "still returns the observed evidence with an explicit notice. This anti-hallucination posture is "
        "enforced in code and covered by unit tests."))
    A(P("Major capabilities (all verified in the codebase):"))
    A(*bullets([
        "Multi-stage LangGraph investigation workflow (8 deterministic nodes) with per-stage tracing and real-time SSE progress streaming to the UI.",
        "RAG over incidents: SentenceTransformer (BAAI/bge-small-en-v1.5, 384-dim) embeddings + embedded Qdrant vector store with payload indexes and a relevance-score threshold.",
        "Deployment correlation via explicit deployment_id, with a documented service-name fallback.",
        "Structured evidence layer (Pydantic models) separating OBSERVED EVIDENCE, RUNBOOK GUIDANCE and AI ANALYSIS in the UI.",
        "Grounded Gemini prompt with retries, timeout, and an evidence-only fallback report.",
        "Per-IP sliding-window rate limiting, strict CORS, structured error envelopes, and fail-soft Langfuse observability.",
        "React 19 chat-style UI with dark/light theme, investigation history, evidence accordions, timeline, and feedback capture.",
        "26/26 pytest tests passing (external services mocked - no API credits consumed); production frontend build verified.",
    ]))
    A(P("<b>Current implementation status:</b> functional single-user prototype running locally. Authentication, "
        "multi-user persistence (database), Docker/CI-CD, and production hosting are not implemented and are "
        "documented in the README as future evolution."))

    A(Paragraph("2. Project Overview", S["H1"]))
    A(Paragraph("2.1 Purpose and Problem Statement", S["H2"]))
    A(P("During production incidents, operations engineers must manually correlate tickets, deployment records, "
        "log files and runbooks across scattered systems. This is slow, error-prone, and often produces "
        "speculative conclusions. The project automates the evidence-gathering and correlation work and produces "
        "a first-draft RCA whose every claim is traceable to retrieved evidence."))
    A(Paragraph("2.2 Objectives", S["H2"]))
    A(*bullets([
        "Automate incident - deployment - log - runbook correlation for any natural-language question.",
        "Ground the LLM strictly in retrieved evidence; never invent incidents, timestamps or root causes.",
        "Make confidence transparent: evidence strength is computed by a deterministic validator, independent of the LLM.",
        "Show real pipeline progress (SSE) rather than fake progress indicators.",
        "Keep observability optional and fail-soft so the pipeline works without external dependencies.",
    ]))
    A(Paragraph("2.3 Scope", S["H2"]))
    A(P("<b>In scope:</b> investigation of incidents recorded in the bundled sample data set (20 incidents, 20 deployments, "
        "550 log lines, 5 markdown runbooks); semantic incident retrieval; structured RCA generation; SSE streaming; "
        "local persistence of history/feedback in the browser."))
    A(P("<b>Out of scope (not identified in the current implementation):</b> live ingestion from ticketing/APM systems, "
        "user accounts/authentication, server-side persistence, multi-tenant support, and production deployment "
        "infrastructure."))
    A(Paragraph("2.4 Target Users and Use Cases", S["H2"]))
    A(table(["Aspect", "Detail"], [
        ["Primary user", "Operations / SRE engineers investigating incidents"],
        ["Secondary users", "Engineering managers reviewing RCA quality; support teams correlating customer issues"],
        ["Use case 1", "\"Why is payroll failing?\" - full RCA with incident, deployment, log and runbook evidence"],
        ["Use case 2", "\"Was the recent deployment responsible for the outage?\" - deployment correlation"],
        ["Use case 3", "\"Analyze authentication failures\" - JWT/auth runbook guidance + related incidents"],
        ["Expected outcome", "Faster triage with a structured, evidence-grounded RCA and an inspectable evidence bundle"],
    ], [35 * mm, W - 35 * mm]))
    A(Paragraph("3. Functional Requirements", S["H1"]))
    A(P("The requirements below are derived directly from the implemented code (routes, workflow nodes, and UI components)."))
    A(table(["ID", "Requirement", "Implementation", "Status"], [
        ["FR-1", "Accept a natural-language investigation question", "POST /investigate and /investigate/stream; Pydantic InvestigateRequest (8-500 chars, non-blank)", "Implemented"],
        ["FR-2", "Stream real workflow progress", "SSE events per LangGraph node completion (NODE_STAGE_IDS); LoadingState renders only backend-confirmed stages", "Implemented"],
        ["FR-3", "Semantic incident retrieval with relevance filtering", "Qdrant cosine search; scores below MIN_RELEVANCE_SCORE (0.30) dropped in incident_agent", "Implemented"],
        ["FR-4", "Correlate incidents with deployments", "deployment_agent: primary by deployment_id; fallback by service only when no ID match", "Implemented"],
        ["FR-5", "Prioritise ERROR/WARN log lines; cap context size", "log_agent regex parser, severity ranking, MAX_LOG_EVIDENCE = 40", "Implemented"],
        ["FR-6", "Retrieve matching runbook as guidance, not evidence", "runbook_agent keyword scoring over 5 curated markdown runbooks", "Implemented"],
        ["FR-7", "Validate evidence and assess strength", "evidence_validation node: deterministic HIGH/MEDIUM/LOW/INSUFFICIENT heuristic", "Implemented"],
        ["FR-8", "Generate grounded RCA via LLM", "gemini_rca_agent structured prompt; markdown parsed into InvestigationResult; confidence clamped by evidence layer", "Implemented"],
        ["FR-9", "Graceful degradation without LLM", "_fallback_result: evidence-only report with explanatory message (verified live)", "Implemented"],
        ["FR-10", "Expose inspectable evidence in the UI", "EvidencePanel accordions with source tags (OBSERVED EVIDENCE / RUNBOOK GUIDANCE / AI ANALYSIS)", "Implemented"],
        ["FR-11", "Persist investigation history and feedback", "localStorage (copilot-history max 20, copilot-feedback max 100); no backend persistence", "Implemented (client-side)"],
        ["FR-12", "Semantic search endpoint", "POST /search: query (2-300 chars), limit (1-20) over the Qdrant collection", "Implemented"],
        ["FR-13", "Health monitoring", "GET /health returns status, qdrant, gemini_configured; UI polls every 30 s", "Implemented"],
        ["FR-14", "User accounts, login, server-side history", "-", "Not identified in the current implementation"],
    ], [12 * mm, 46 * mm, W - 80 * mm, 22 * mm]))

    A(Paragraph("4. Non-Functional Requirements", S["H1"]))
    A(table(["Category", "Observed in Implementation", "Assessment"], [
        ["Performance", "Data files cached via lru_cache; embedding model loaded once at import; SSE streams stage-by-stage; 180 s client timeout for LLM latency; stage timings logged in ms", "Good for prototype scale"],
        ["Scalability", "Embedded Qdrant and in-memory rate limiter are single-process only; README documents Qdrant server mode for multi-instance", "Limited - see Section 24"],
        ["Security", "Strict CORS allow-list (no wildcard); rate limiting on expensive endpoints; generic error envelopes; no secrets in code; input length validation mirrored front/back", "Solid basics; no authentication yet"],
        ["Reliability", "Defensive nodes record failures and continue; Gemini retry x3 + fallback; Langfuse fail-soft; Qdrant collection auto-created on startup if missing", "Strong failure isolation"],
        ["Maintainability", "Single config module; typed Pydantic contracts between stages; docstrings; modular agents; 26 unit tests", "High"],
        ["Usability", "Chat UI, example prompts, live stage progress, dark/light theme, evidence accordions, searchable history", "High"],
        ["Availability", "Single local uvicorn process; health endpoint exists but no orchestrator/restart policy", "Not addressed - recommendation"],
        ["Accessibility", "aria-labels/roles on key controls (input, toggles, status pill, aria-live loading)", "Partially addressed"],
        ["Data integrity", "Deterministic UUIDv5 point IDs make seeding idempotent; timeline built only from real timestamps; seed validates required fields", "Good within file-based scope"],
    ], [24 * mm, (W - 24 * mm) * 0.62, (W - 24 * mm) * 0.38]))
    return s