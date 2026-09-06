"""Report content part 13: sections 32-34."""
from generate_report import S, P, bullets, table, Paragraph, W, mm

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("32. Maintenance & Support", S["H1"]))
    A(table(["Area", "Guidance"], [
        ["Configuration", "All runtime settings live in backend/config.py sourced from environment variables (see Appendix); the frontend has a single variable, VITE_API_URL"],
        ["Important modules", "workflows/rca_graph.py (pipeline), agents/* (retrieval and generation), vector_store/* (search), utils/rate_limit.py (abuse protection), observability/* (tracing)"],
        ["Common tasks", "Add an incident: append to data/incidents.json and re-run python -m scripts.seed. Add a runbook: drop a markdown file into data/runbooks/ and add its domain keywords to RUNBOOK_KEYWORDS. Clear data caches: utils.data_store.refresh_data_cache()"],
        ["Vector store maintenance", "Embedded Qdrant data lives in backend/qdrant_data - back it up or re-seed deterministically; verify counts via the seed script's built-in check"],
        ["Deployment maintenance", "Run uvicorn under a process manager; LOG_LEVEL=INFO in production; rotate the Gemini key via environment only"],
        ["Logging", "Root logger configured in config.py; stage timings logged in ms - watch 'Stage ... completed in ... ms' lines for latency regressions"],
        ["Troubleshooting", "qdrant=false in /health - check qdrant_data or re-run the seed. gemini_configured=false - set GEMINI_API_KEY. HTTP 429 - rate limit reached. RCA with a notice banner - Gemini failed and the evidence-only fallback was returned"],
        ["Special attention", "Never log or commit secrets; keep evidence caps aligned when changing prompt size; keep the frontend STAGES list in sync with backend NODE_STAGE_IDS"],
    ], [34 * mm, W - 34 * mm]))

    A(Paragraph("33. GitHub / Repository Readiness", S["H1"]))
    A(table(["Item", "Assessment"], [
        ["README", "Excellent: architecture diagram, tech stack, structure, setup, environment variables, API table, test command, production considerations, future evolution"],
        [".gitignore", "Present at root and in frontend; node_modules, dist, .env and caches excluded"],
        ["Dependency files", "requirements.txt fully pinned; package-lock.json committed"],
        ["Secrets", "No secrets in the repository; .env.example placeholders only; frontend/.env holds a non-secret URL and is local-only"],
        ["Tests", "26 backend tests included and passing; no frontend tests"],
        ["Scripts", "seed.py gives reproducible vector-store setup; npm scripts are standard"],
        ["Generated files", "qdrant_data/, dist/, __pycache__ exist locally (git-ignored); stray logs (uv_*.log, npm_install*.log) in the parent folder - move or delete before publishing"],
        ["Reproducibility", "High: pinned dependencies + deterministic seeding + mocked tests; a fresh clone reproduces behaviour given a Gemini key"],
        ["Overall readiness", "Good for a portfolio repository after removing local logs/artifacts and fixing the lint script; production readiness requires auth, Docker and CI (Section 30)"],
    ], [30 * mm, W - 30 * mm]))

    A(Paragraph("34. Resume / Portfolio Value", S["H1"]))
    A(table(["Skill", "Evidence in the Project"], [
        ["Full-stack development", "Complete React 19 SPA + FastAPI service delivering one product end to end"],
        ["AI / RAG engineering", "Qdrant vector store, bge-small embeddings, relevance gating, grounded Gemini prompting, confidence clamping, evidence-only fallback"],
        ["Multi-agent & workflow orchestration", "LangGraph StateGraph with typed state, fault-isolated nodes and stage-level observability"],
        ["API development", "FastAPI with Pydantic contracts, SSE streaming, uniform error envelopes, Swagger docs, rate limiting"],
        ["Python backend engineering", "Modular package design, lru_cache data caching, defensive error handling, configuration discipline"],
        ["React / modern frontend", "Hooks-based architecture, SSE parsing over fetch streams, accessible components, theming"],
        ["Observability", "Optional Langfuse tracing with fail-soft design and per-stage timing instrumentation"],
        ["Testing / QA", "26-test pytest suite mocking external services; assertion of security-relevant behaviours (error leakage, rate limiting)"],
        ["Security fundamentals", "CORS allow-listing, secrets management, input validation, data minimisation in traces"],
        ["Data engineering (light)", "Deterministic idempotent seeding pipeline with validation and verification"],
        ["Technical documentation", "Accurate README plus this evidence-based technical report"],
    ], [44 * mm, W - 44 * mm]))
    return s