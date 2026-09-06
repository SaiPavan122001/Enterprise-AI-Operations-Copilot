"""Report content part 9: sections 21-22."""
from generate_report import S, P, bullets, table, Paragraph, W, mm

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("21. Testing", S["H1"]))
    A(P("The project ships a pytest suite (backend/tests) with external services (Qdrant, Gemini, LangGraph) mocked, "
        "so no API credits are consumed and no network is required. The suite was executed as part of this report's "
        "verification."))
    A(table(["File", "Scope", "Notable Assertions"], [
        ["tests/conftest.py", "Makes the backend package importable from any working directory; quiets logging", "-"],
        ["tests/test_api.py (11 tests)", "Health endpoint; /investigate validation (missing/short/blank/overlong question); structured payload shape; validation block; no raw exception leakage on workflow failure; rate limiting (3rd request - 429); /search validation and limit bounds", "Error messages are user-safe; markdown fallback present; rate limit enforced"],
        ["tests/test_agents.py (15 tests)", "Deployment correlation by id and service fallback; log parsing/prioritisation/keyword fallback; runbook matching (payroll, jwt, unrelated); timeline uses only real timestamps; evidence layer authority over confidence; Gemini success parse and failure fallback", "No invented root cause on failure; confidence clamped; chronological timeline"],
    ], [40 * mm, (W - 40 * mm) * 0.55, (W - 40 * mm) * 0.45]))
    A(P("<b>Actual result (run for this report):</b> <font color='#0FA47F'><b>26 passed, 2 warnings in 28.83 s</b></font> "
        "(pytest 8.3.4, Python 3.12.10). The two warnings are third-party deprecations inside langgraph and "
        "starlette's test client - not project issues. No frontend unit/E2E tests exist (npm scripts provide dev, "
        "build, lint, preview only)."))

    A(Paragraph("22. Verification & Quality Assurance", S["H1"]))
    A(P("Every row below was executed during the preparation of this report on the actual workspace."))
    A(table(["Verification", "Command / Method", "Result", "Status"], [
        ["Backend test suite", "python -m pytest tests/ -v (backend/)", "26 passed, 2 warnings in 28.83 s", "Pass"],
        ["Frontend production build", "npm run build (frontend/)", "201 modules transformed; dist/ generated; JS 337.10 kB (gzip 104.72 kB); built in 1.00 s; exit code 0", "Pass"],
        ["Backend startup", "python -m uvicorn app:app --port 8017", "Uvicorn running; lifespan warmed cache; Qdrant collection validated", "Pass"],
        ["Health endpoint", "GET http://127.0.0.1:8017/health", "status=healthy, qdrant=true, gemini_configured=false", "Pass"],
        ["Semantic search endpoint", "POST /search {query: 'payroll failing', limit: 3}", "status=success, 3 scored results returned", "Pass"],
        ["Investigation without Gemini key", "POST /investigate (payroll question)", "Graceful fallback: status=error, confidence LOW clamped while evidence_strength HIGH preserved, message 'AI analysis is temporarily unavailable...' - observed evidence still returned", "Pass (fallback path)"],
        ["Log evidence prioritisation", "agents/log_agent.py + unit tests", "ERROR/WARN prioritised, 40-line cap", "Pass"],
        ["Secrets scan", "Inspection of .env files, .gitignore, source", "frontend/.env contains only VITE_API_URL; backend .env absent; .env.example placeholders only", "Pass"],
        ["Lint", "npm run lint", "ESLint 9 flat-config fails to load under the installed Node 24 environment (config-loader error)", "Fail - see limitations"],
        ["Seed re-run", "python -m scripts.seed (documented command)", "Not re-run in this analysis; idempotent design verified by code review (uuid5 ids, count check)", "Not re-run"],
        ["Gemini generation with a real key", "requires GEMINI_API_KEY", "Key not present in this workspace - generation path verified via mocks and the fallback path live", "Not verified live"],
    ], [32 * mm, (W - 32 * mm) * 0.32, (W - 32 * mm) * 0.44, (W - 32 * mm) * 0.24]))
    return s