"""Report content part 8: sections 19-20."""
from generate_report import S, P, bullets, table, Paragraph, W, mm

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("19. Validation & Error Handling", S["H1"]))
    A(table(["Layer", "Mechanism"], [
        ["API input validation", "Pydantic Field constraints (question 8-500, query 2-300, limit 1-20) + field_validator rejecting blank/whitespace; returns 422 with a generic user-safe message while details go to logs"],
        ["Frontend validation", "maxLength 500 on the textarea, non-blank submit guard, live counter; matches backend limits by design"],
        ["Vector store validation", "Seed script requires id/service/severity/status/title/root_cause and aborts on missing fields; verifies stored count after upsert"],
        ["Workflow exceptions", "Each LangGraph node catches its own exceptions, stores empty results, appends the stage to errors - partial evidence still produces a report"],
        ["API error responses", "Dedicated handlers for HTTPException, RequestValidationError and Exception; uniform {status, message}; a unit test asserts internal error text never leaks into the 500 body"],
        ["External service failures", "Gemini: 3 attempts then evidence-only fallback (verified live). Langfuse: every call wrapped, failures logged as warnings"],
        ["Retry logic", "GEMINI_MAX_RETRIES (default 2, i.e. 3 attempts) with per-attempt logging"],
        ["Fallbacks", "Qdrant collection auto-created at startup if missing; UI falls back from streaming to non-streaming investigate(); localStorage quota fallback stores metadata only"],
        ["Logging", "Root logging configured in config.py; httpx/httpcore/urllib3 noise suppressed; stage timings logged in ms; rate-limit violations warned"],
        ["Recovery", "Stateless API - failed requests can simply be retried; rate-limiter window self-expires; refresh_data_cache() supports hot data reload"],
    ], [38 * mm, W - 38 * mm]))

    A(Paragraph("20. Security Analysis", S["H1"]))
    A(Paragraph("20.1 Implemented Security", S["H2"]))
    A(*bullets([
        "<b>Secrets management:</b> keys only via environment variables (backend .env, frontend VITE_API_URL); .env files are git-ignored; .env.example contains placeholders only. No API keys, passwords or tokens are hardcoded anywhere in the repository (verified by inspection).",
        "<b>CORS:</b> explicit allow-list from CORS_ORIGINS (default localhost:5173 / 127.0.0.1:5173); methods limited to GET/POST; headers limited to Authorization/Content-Type; no wildcard.",
        "<b>Rate limiting:</b> per-IP sliding window (10/60 s default) on the expensive LLM endpoints to bound API spend.",
        "<b>Input validation:</b> strict Pydantic bounds mirrored on the client; prompt-injection surface reduced by capping and structuring all context fed to Gemini.",
        "<b>Error hygiene:</b> internal exceptions and stack traces are logged, never returned; a unit test explicitly asserts no internal detail leaks in the 500 body.",
        "<b>Data minimisation:</b> Langfuse traces record question length, not the question text.",
        "<b>Parsing safety:</b> unparseable log lines are preserved verbatim rather than interpreted; no eval or dynamic execution exists in the codebase.",
        "<b>Injection:</b> no SQL is used; Qdrant queries use typed filter objects, not string interpolation.",
    ]))
    A(Paragraph("20.2 Recommended Security Improvements", S["H2"]))
    A(*bullets([
        "<b>Authentication &amp; authorization:</b> none today - required before any deployment beyond localhost (the README acknowledges this). Recommended: token/OAuth-based auth with protected routes.",
        "<b>XSS:</b> React escapes interpolated content by default and react-markdown is used without custom HTML rendering; still, a strict Content-Security-Policy is recommended for defence in depth.",
        "<b>CSRF:</b> low risk with the current no-cookie design; becomes relevant once cookie sessions are introduced.",
        "<b>Rate limiter scope:</b> in-memory and per-process - a distributed deployment needs a shared store (e.g. Redis) and a defined X-Forwarded-For trust policy.",
        "<b>Dependency security:</b> no automated scanning (pip-audit / npm audit / Dependabot) is configured.",
        "<b>Transport security:</b> no HTTPS/TLS configuration - required for any hosted deployment.",
    ]))
    return s