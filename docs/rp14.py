"""Report content part 14: sections 35-36 (final summary + appendix)."""
from generate_report import S, P, bullets, table, Paragraph, W, mm

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("35. Final Technical Summary", S["H1"]))
    A(table(["Dimension", "Summary"], [
        ["Architecture", "React 19 SPA - FastAPI - LangGraph 8-node pipeline - Qdrant (embedded) + file data store - Gemini LLM; SSE progress streaming; fail-soft optional Langfuse tracing"],
        ["Technology", "Python 3.12 / FastAPI 0.115 / LangGraph 0.2 / qdrant-client 1.12 / sentence-transformers 3.3 / google-genai 0.6 / React 19 / Vite 6 (all pinned)"],
        ["Features", "Grounded RCA generation, RAG incident retrieval with thresholding, deployment correlation, log/runbook evidence, evidence validation, streaming UI, history, feedback, health monitoring"],
        ["Data flow", "question - keywords - agents - EvidenceBundle - EvidenceValidation - Gemini - InvestigationResult - SSE/JSON - React UI - localStorage; uniform error envelope everywhere"],
        ["Security", "Implemented: CORS allow-list, rate limiting, secrets hygiene, input validation, user-safe errors, trace minimisation. Missing: authentication, HTTPS, dependency scanning"],
        ["Testing", "26/26 pytest tests passing in 28.83 s (services mocked); frontend verified via production build; no frontend test suite"],
        ["Performance", "Small bundle (337 kB / 105 kB gzip); cached data; bounded prompts; LLM call is the dominant latency and is instrumented per stage"],
        ["Deployment", "Local-process only today; Docker/CI/cloud documented as future work; idempotent seeding and health endpoint ready for orchestration"],
        ["Current status", "Functional, tested prototype (v1.1.0) - strong engineering foundations; authentication and persistence are the gating items for production"],
    ], [30 * mm, W - 30 * mm]))

    A(Paragraph("36. Appendix", S["H1"]))
    A(Paragraph("A. API Summary", S["H2"]))
    A(P("GET /health - status, qdrant, gemini_configured. POST /search - semantic incident search (query 2-300, limit 1-20). "
        "POST /investigate - synchronous RCA. POST /investigate/stream - SSE RCA with per-stage events. "
        "All errors: {\"status\": \"error\", \"message\"}. Rate limit: 10/60 s per IP on both /investigate endpoints."))
    A(Paragraph("B. Data Summary", S["H2"]))
    A(P("Qdrant collection enterprise_incidents (384-dim cosine, payload indexes service/severity/status) seeded from "
        "data/incidents.json (20 incidents, required fields id/service/severity/status/title/root_cause). "
        "data/deployments.json: 20 deployments joined by deployment_id. data/logs.txt: 550 lines parsed by regex. "
        "data/runbooks: 5 markdown runbooks (database_timeout, email_delivery_failure, gateway_outage, jwt_auth_failure, "
        "payment_failure)."))
    A(Paragraph("C. Environment Variable Names (values never documented)", S["H2"]))
    A(P("Backend: GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TIMEOUT_MS, GEMINI_MAX_RETRIES, LANGFUSE_PUBLIC_KEY, "
        "LANGFUSE_SECRET_KEY, LANGFUSE_HOST, CORS_ORIGINS, QDRANT_PATH, QDRANT_COLLECTION, INVESTIGATE_RATE_LIMIT, "
        "INVESTIGATE_RATE_WINDOW_SECONDS, QUESTION_MIN_LENGTH, QUESTION_MAX_LENGTH, MIN_RELEVANCE_SCORE, LOG_LEVEL. "
        "Frontend: VITE_API_URL.", "P"))
    A(Paragraph("D. Key Configuration Defaults", S["H2"]))
    A(table(["Setting", "Default"], [
        ["GEMINI_MODEL", "gemini-2.5-flash"],
        ["GEMINI_TIMEOUT_MS / MAX_RETRIES", "60000 / 2 (3 attempts)"],
        ["CORS_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173"],
        ["INVESTIGATE_RATE_LIMIT / WINDOW", "10 / 60 s"],
        ["QUESTION_MIN / MAX_LENGTH", "8 / 500"],
        ["MIN_RELEVANCE_SCORE", "0.30 (HIGH requires 0.45)"],
        ["QDRANT_PATH / COLLECTION", "backend/qdrant_data / enterprise_incidents"],
        ["Evidence caps", "5 incidents, 5 deployments, 40 log lines (30 to prompt), 3000-4000 runbook chars, 15 timeline events"],
    ], [70 * mm, W - 70 * mm]))
    A(Paragraph("E. Glossary", S["H2"]))
    A(*bullets([
        "<b>RCA</b> - Root Cause Analysis: structured investigation of why an incident happened.",
        "<b>RAG</b> - Retrieval-Augmented Generation: grounding an LLM in retrieved documents.",
        "<b>Evidence strength</b> - validator-computed quality level (HIGH/MEDIUM/LOW/INSUFFICIENT) of retrieved evidence.",
        "<b>SSE</b> - Server-Sent Events: one-way HTTP streaming used for live pipeline progress.",
        "<b>MCP</b> - Model Context Protocol: standard protocol for exposing tools to LLM agents (FastMCP server here).",
        "<b>Embedded Qdrant</b> - Qdrant running in-process against a local file path instead of a server.",
        "<b>Langfuse</b> - LLM observability platform for traces, spans and evaluations.",
    ]))
    A(Paragraph("F. Verification Information", S["H2"]))
    A(P("This report was generated from a static analysis of the full codebase plus live verification on "
        "September 4, 2026: pytest run (26/26 passed), npm production build (successful), backend startup and "
        "health/search/investigate endpoint probes (all behaved as designed, including the Gemini-fallback path). "
        "No secrets were collected or reproduced. Sections marked 'Not identified in the current implementation' "
        "or 'Not verified live' reflect genuine gaps rather than assumptions."))
    return s