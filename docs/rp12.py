"""Report content part 12: sections 30-31."""
from generate_report import S, P, bullets, table, Paragraph, W, mm

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("30. Recommended Improvements", S["H1"]))
    A(Paragraph("30.1 High Priority", S["H2"]))
    A(*bullets([
        "<b>Add authentication and authorization</b> (JWT or OAuth via FastAPI dependencies) before any non-local deployment. Why: without it, anyone can spend the Gemini quota and read enterprise incident data.",
        "<b>Harden rate limiting and add a global spend cap</b> (Redis-backed limiter + daily LLM budget). Why: the in-memory limiter does not survive restarts or multiple workers, and a per-IP limit does not bound total cost.",
        "<b>Fix the lint toolchain</b> (pin compatible ESLint/Node versions or migrate the flat config). Why: CI cannot enforce code quality until lint runs.",
    ]))
    A(Paragraph("30.2 Medium Priority", S["H2"]))
    A(*bullets([
        "<b>Introduce server-side persistence</b> (PostgreSQL/Supabase for users, investigations, feedback). Why: replaces localStorage-only history and enables multi-user analytics (the README already plans this).",
        "<b>Dockerise backend and frontend</b> with a compose file including a Qdrant server. Why: reproducible environments and a path to cloud deployment.",
        "<b>Add a CI pipeline</b> (GitHub Actions: pytest + npm build + lint). Why: keeps the 26-test suite meaningful on every commit.",
        "<b>Upgrade retrieval quality:</b> embed runbooks for semantic matching; consider hybrid (vector + keyword) log retrieval. Why: removes dependence on hand-maintained keyword maps.",
        "<b>Wire up or remove the MCP server.</b> Why: it currently duplicates access logic with no consumer.",
        "<b>Unify version strings</b> (1.1.0 vs Sidebar v1.2.0). Why: confusing for users and support.",
    ]))
    A(Paragraph("30.3 Low Priority", S["H2"]))
    A(*bullets([
        "Cache Gemini responses for identical questions (dedup + cost saving).",
        "Stream the markdown report at token level to further reduce perceived latency.",
        "Add structured JSON logging with request-ID correlation across stages.",
        "Deepen accessibility (focus trapping in the sidebar overlay, keyboard navigation for accordions).",
        "Normalise non-ASCII UI strings to avoid mojibake across encodings.",
    ]))

    A(Paragraph("31. Future Enhancements", S["H1"]))
    A(P("Realistic extensions that fit the existing architecture (all are recommendations, not implemented features):"))
    A(*bullets([
        "<b>Live data ingestion:</b> connectors to ticketing (Jira/ServiceNow), APM (Datadog, Prometheus) and log platforms feeding the same evidence models.",
        "<b>Multi-user RCA workspace:</b> per-user investigation threads, sharing, and RCA review/approval workflows on top of the planned persistence layer.",
        "<b>Agent-mode investigations:</b> use the existing FastMCP tools with an agentic loop (function calling) for multi-step, exploratory RCAs.",
        "<b>Feedback-driven improvement loop:</b> export the already-captured feedback to Langfuse datasets and evaluate prompt variants against them.",
        "<b>Deployment-risk scoring:</b> correlate historical incident rates per service/deployment to flag risky changes.",
        "<b>Postgres pgvector option:</b> consolidate vectors and relational data once the database layer exists.",
        "<b>Notification integrations:</b> push finished RCAs to Slack/Teams webhooks.",
    ]))
    return s