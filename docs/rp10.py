"""Report content part 10: sections 23-26."""
from generate_report import S, P, bullets, table, Paragraph, W, mm, diag, d_deploy

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("23. Performance Analysis", S["H1"]))
    A(P("No formal benchmark suite exists in the repository; the observations below come from the live run performed "
        "for this report plus design-level analysis. Per-request timings were not captured into a benchmark "
        "artefact and are therefore not fabricated."))
    A(table(["Aspect", "Observation / Design Evidence"], [
        ["Frontend bundle", "337.10 kB JS (104.72 kB gzip) + 18.48 kB CSS (4.32 kB gzip) - small single-page bundle; 1.00 s production build"],
        ["Static data access", "lru_cache(1) means deployments/logs/runbooks are read from disk once per process, not per request"],
        ["Embedding cost", "SentenceTransformer instantiated once at import; per-query encoding is a single 384-dim inference (tens of milliseconds on CPU for short queries)"],
        ["Vector search", "Embedded Qdrant over 20 points with payload indexes - very fast at this scale; designed to scale with server mode"],
        ["LLM latency", "Dominant cost: gemini-2.5-flash call, timeout 60 s; the UI allows 180 s. Stage timings are logged in ms by InvestigationTracer (and visible in Langfuse when configured)"],
        ["Streaming", "SSE keeps the user informed during long generations instead of a blocking spinner"],
        ["Memory", "Embedding model + 550 log lines + JSON data are small; the in-memory rate limiter grows with distinct client IPs (unbounded - see Section 24)"],
        ["Large-data behaviour", "Evidence caps bound prompt size regardless of data growth: 5 incidents, 5 deployments, 40 log lines, 4000 runbook chars"],
    ], [30 * mm, W - 30 * mm]))

    A(Paragraph("24. Scalability", S["H1"]))
    A(table(["Dimension", "Current Behaviour", "Bottleneck / Recommendation"], [
        ["Users increase", "Single uvicorn process; stateless API", "Run multiple workers/instances; move the rate limiter to Redis"],
        ["Data increase", "Embedded Qdrant file-backed collection; lru_cache assumes data fits in memory", "Switch to Qdrant server mode (QDRANT_URL); move data files to a database; add incremental indexing"],
        ["API traffic", "FastAPI + Pydantic are efficient; the heavy work is the LLM call", "Queue investigations (e.g. Celery/RQ) instead of holding HTTP connections; horizontal scaling behind a load balancer"],
        ["Concurrent requests", "SSE holds one connection per active investigation", "Worker/threadpool sizing; consider WebSockets with backpressure at larger scale"],
        ["AI usage increase", "Rate limit (10/60 s per IP) bounds per-client spend but not global spend", "Add a global budget/quota, response caching for repeated questions, and a cheaper model tier for triage"],
    ], [26 * mm, (W - 26 * mm) * 0.48, (W - 26 * mm) * 0.52]))

    A(Paragraph("25. Deployment & DevOps", S["H1"]))
    A(*diag(d_deploy, 90, "Figure 5 - Current deployment topology (local process, external SaaS LLM/observability)"))
    A(table(["Concern", "Status in This Project"], [
        ["Build", "Frontend: npm run build (Vite, verified). Backend: none needed (interpreted Python)"],
        ["Environment configuration", ".env files per tier; .env.example templates; config.py resolves repo-root or backend .env automatically"],
        ["Docker", "Not identified in the current implementation (no Dockerfile/compose)"],
        ["CI/CD", "Not identified in the current implementation (no pipeline config in the repository)"],
        ["Hosting platform", "Local machine only (uvicorn + Vite); no cloud deployment configured"],
        ["Database deployment", "Embedded Qdrant directory backend/qdrant_data; no managed database"],
        ["Environment variables", "Backend: GEMINI_API_KEY (required), LANGFUSE_*, CORS_ORIGINS, GEMINI_MODEL/TIMEOUT_MS/MAX_RETRIES, QDRANT_PATH/COLLECTION, INVESTIGATE_RATE_*, QUESTION_MIN/MAX_LENGTH, MIN_RELEVANCE_SCORE, LOG_LEVEL. Frontend: VITE_API_URL"],
        ["Monitoring", "Structured Python logging + optional Langfuse tracing; GET /health for probes; no external monitoring/alerting"],
        ["Production configuration guidance", "README documents: real CORS origins, auth requirement, Qdrant server mode, process manager, LOG_LEVEL=INFO"],
    ], [34 * mm, W - 34 * mm]))

    A(Paragraph("26. Installation & Setup", S["H1"]))
    A(P("The steps below are taken from the project README and verified against the codebase."))
    A(Paragraph("Prerequisites", S["H3"]))
    A(*bullets([
        "Python 3.12 (verified on 3.12.10), Node.js 18+ (verified on v24.19.0), npm.",
        "A Google Gemini API key (GEMINI_API_KEY) for LLM generation; Langfuse keys optional.",
    ]))
    A(Paragraph("Backend", S["H3"]))
    A(Paragraph("cd backend<br/>pip install -r requirements.txt<br/>"
                "copy ../.env.example .env   # then set GEMINI_API_KEY<br/>"
                "python -m scripts.seed      # validate, embed, upsert incidents into Qdrant<br/>"
                "uvicorn app:app --reload    # http://127.0.0.1:8000 - Swagger at /docs", S["Code"]))
    A(Paragraph("Frontend", S["H3"]))
    A(Paragraph("cd frontend<br/>npm install<br/>copy .env.example .env    # VITE_API_URL=http://127.0.0.1:8000<br/>"
                "npm run dev                # http://localhost:5173", S["Code"]))
    A(Paragraph("Tests and production build", S["H3"]))
    A(Paragraph("cd backend && python -m pytest tests/ -v   # 26 tests, external services mocked<br/>"
                "cd frontend && npm run build              # outputs dist/", S["Code"]))
    A(P("<b>Database setup</b> consists solely of the seed step above - the Qdrant collection is created "
        "automatically at app startup if missing, and the seed script is idempotent (deterministic UUIDv5 point ids)."))
    return s