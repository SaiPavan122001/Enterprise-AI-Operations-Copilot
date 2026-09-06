"""Report content part 11: sections 27-29."""
from generate_report import S, P, bullets, table, Paragraph, W, mm

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("27. Problems Found & Improvements Made", S["H1"]))
    A(P("Git history shows a single initial commit (v1.0.0) with substantial uncommitted restructuring: early "
        "experimental modules (backend/rag/*, backend/embeddings/*, ad-hoc test scripts) were deleted and replaced "
        "by the current structured architecture (config.py, models/, utils/, observability/, tests/). Because "
        "history cannot establish before/after behaviour, items below are documented as engineering improvements "
        "visible in the current design, or as potential issues identified during analysis - not as verified "
        "historical fixes."))
    A(table(["Problem / Improvement", "Cause", "Solution (as implemented)", "Result"], [
        ["Unstructured dict passing between pipeline stages (removed design)", "Early RAG modules passed arbitrary dictionaries", "Typed Pydantic evidence layer (models/evidence.py) is now the contract between agents, validation, LLM and API", "Design improvement; each agent unit-testable in isolation"],
        ["Hallucination risk in LLM RCAs", "LLMs can claim high confidence without evidence", "Deterministic evidence-validation node + _final_confidence clamping + strict prompt rules", "Verified by unit tests (authority test; failure test asserts no invented root cause)"],
        ["Raw exceptions leaking to users", "Typical default FastAPI behaviour", "Global handlers normalise every error into {status, message}; details only in logs", "Verified: test_no_raw_exception_on_workflow_failure passes"],
        ["Unbounded LLM spend", "Expensive Gemini calls on a public endpoint", "Per-IP sliding-window rate limiter (default 10/60 s)", "Verified: test_rate_limiting passes (3rd request - 429)"],
        ["Silent observability failures", "Optional Langfuse could break the pipeline", "Defensive client init + noop spans; every tracing call wrapped", "Design-level; app ran here with Langfuse unconfigured and no errors"],
        ["<b>Potential issue:</b> unbounded in-memory rate-limiter map", "RateLimiter keeps every client IP forever", "None yet - add pruning or an LRU bound", "Open"],
        ["<b>Potential issue:</b> lint script broken in current environment", "ESLint 9 flat-config fails to load under the installed Node toolchain", "None yet - pin a compatible ESLint/Node pair or update the config", "Open (verified failing)"],
        ["<b>Potential issue:</b> non-ASCII mojibake in a few UI literals", "Windows encoding of special characters in JSX strings", "None yet - normalise to ASCII or enforce UTF-8 toolchain-wide", "Open (cosmetic)"],
    ], [40 * mm, (W - 40 * mm) * 0.22, (W - 40 * mm) * 0.24, (W - 40 * mm) * 0.14]))
    A(Paragraph("28. Current Strengths", S["H1"]))
    A(*bullets([
        "<b>Architecture:</b> clean layering (API - workflow - agents - data) with typed Pydantic contracts; a deterministic 8-node graph instead of a free-form agent loop makes behaviour predictable and testable.",
        "<b>Honesty-by-design:</b> the strongest engineering decision in the project - evidence strength gates LLM confidence, timelines use only real timestamps, runbooks are quarantined as guidance, and the fallback path returns evidence without AI inference.",
        "<b>Operational resilience:</b> every external dependency (Gemini, Langfuse, Qdrant) fails soft or falls back; nodes are individually fault-isolated.",
        "<b>Testability:</b> 26 fast, credit-free tests pinning down the most safety-critical behaviours (confidence clamping, error envelopes, rate limiting, timeline integrity).",
        "<b>Code organisation:</b> single config source; pinned dependencies; intent-documenting docstrings; deprecated entry points kept as thin wrappers rather than dead code.",
        "<b>UI/UX:</b> chat-style experience with live pipeline progress, inspectable evidence accordions with source labels, searchable history, theming and accessible controls - unusually mature for a prototype.",
        "<b>Security basics:</b> strict CORS, rate limiting, secrets discipline and user-safe errors done correctly from the start.",
        "<b>Documentation:</b> the README accurately describes architecture, endpoints, environment variables, tests and production considerations - it matches the code (verified during this analysis).",
    ]))

    A(Paragraph("29. Known Limitations", S["H1"]))
    A(table(["Severity", "Limitation"], [
        ["Critical (for public use)", "No authentication or authorization - anyone who can reach the API can invoke Gemini-backed investigations and consume the API key's quota"],
        ["High", "No server-side persistence: history, feedback and multi-user state live only in the browser; the data set is a fixed sample, not a live telemetry feed"],
        ["High", "Single-process constraints: embedded Qdrant and in-memory rate limiter prevent horizontal scaling"],
        ["Medium", "No Docker/CI-CD, HTTPS, or monitoring/alerting; the deployment story is local-only"],
        ["Medium", "Runbook and log retrieval are keyword heuristics (not semantic) - recall depends on curated keyword maps; question analysis is a stopword tokenizer, not an NLP model"],
        ["Medium", "npm run lint fails in the current environment (ESLint 9 flat-config load error under Node 24)"],
        ["Low", "Minor non-ASCII mojibake in a few UI literals; version inconsistency (Sidebar shows v1.2.0, package.json/app are 1.1.0)"],
        ["Low", "Feedback component stores locally only; App passes a no-op onFeedback callback"],
    ], [34 * mm, W - 34 * mm]))
    return s
    return s
