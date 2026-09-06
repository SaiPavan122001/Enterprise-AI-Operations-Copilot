"""Report content part 4: sections 11-13."""
from generate_report import S, P, bullets, table, Paragraph, W, mm

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("11. API Documentation", S["H1"]))
    A(table(["Method", "Endpoint", "Purpose", "Auth", "Request", "Response", "Errors"], [
        ["GET", "/health", "Liveness + dependency status", "None", "-", "{status, qdrant: bool, gemini_configured: bool}", "500 generic"],
        ["POST", "/search", "Semantic incident search", "None", "{query: 2-300 chars, limit: 1-20 (default 5)}", "{status, results: [payloads]}", "422; 500 generic"],
        ["POST", "/investigate", "Full synchronous RCA", "None", "{question: 8-500 chars, non-blank}", "{status, investigation, report, message}", "422; 429 rate limit; 500 generic"],
        ["POST", "/investigate/stream", "SSE RCA with live stage events", "None", "{question: 8-500 chars}", "SSE: investigation_started, one <stage>_completed per node, investigation_completed (full payload) or investigation_error", "429; SSE investigation_error"],
    ], [11 * mm, 28 * mm, 25 * mm, 10 * mm, 34 * mm, W - 108 * mm - 16 * mm, 16 * mm]))
    A(P("The <b>investigation</b> object (InvestigationResult) contains: question, status, summary, impact, root_cause, "
        "confidence, evidence_strength, contributing_factors, recommended_remediation, preventive_actions, "
        "observed_evidence, investigation_details, timeline[], evidence (EvidenceBundle) and validation "
        "(EvidenceValidation). report is the same RCA as markdown for fallback rendering. Rate limiting: "
        "10 requests / 60 s per IP by default (configurable). Interactive docs are auto-generated at /docs (Swagger). "
        "Every error response uses the same envelope: {\"status\": \"error\", \"message\": \"...\"}."))

    A(Paragraph("12. Data Architecture", S["H1"]))
    A(P("There is no relational database. Data lives in three shapes, all local: a vector collection, flat files, "
        "and browser localStorage."))
    A(table(["Store", "Shape", "Key fields", "Relationships / Constraints"], [
        ["Qdrant collection 'enterprise_incidents'", "384-dim vectors + JSON payload, cosine distance", "incident_id, deployment_id, service, severity, status, title, root_cause", "Payload keyword indexes on service/severity/status; deterministic UUIDv5 point ids (idempotent re-seeding); record count verified after seeding"],
        ["data/incidents.json (20 records)", "JSON array", "id, service, severity, status, title, root_cause, deployment_id", "Seed script fails on missing required fields; deployment_id references deployments.json"],
        ["data/deployments.json (20 records)", "JSON array", "deployment_id, service, time, change", "Joined to incidents via deployment_id"],
        ["data/logs.txt (550 lines)", "Plain text lines", "timestamp, service, LEVEL, message", "Parsed by regex; unparseable lines preserved verbatim (never fabricated fields)"],
        ["data/runbooks/*.md (5 files)", "Markdown", "title heading + procedural content", "Mapped to domains in runbook_agent.RUNBOOK_KEYWORDS"],
        ["Browser localStorage", "JSON strings", "copilot-history (max 20), copilot-feedback (max 100), copilot-theme", "Quota-exceeded fallback stores metadata only"],
    ], [36 * mm, 30 * mm, 44 * mm, W - 110 * mm]))
    A(P("<b>Relationships:</b> Incident (1) - deployment_id - (1) Deployment; log lines relate to services mentioned in "
        "incidents/deployments; runbooks relate to question/incident domain keywords. <b>A traditional ER diagram is "
        "not applicable</b> because the stores are a vector collection plus flat files; primary keys are incident.id "
        "(and its derived Qdrant point id) and deployment.deployment_id. There are no SQL indexes, foreign keys or "
        "row-level security policies - the only indexes are the Qdrant payload indexes listed above."))

    A(Paragraph("13. Authentication & Authorization", S["H1"]))
    A(P("<b>Not identified in the current implementation.</b> The API has no registration, login, sessions, tokens, "
        "password handling, roles, permissions or protected routes. This is a deliberate, documented decision for "
        "the prototype: the README explicitly states that authentication must be added before any public "
        "deployment and that rate limiting alone does not prevent abuse. The CORS middleware does allow the "
        "Authorization header, showing the design anticipates adding token-based auth later. "
        "Authorization is therefore covered in the Recommended Improvements (Section 30)."))
    return s