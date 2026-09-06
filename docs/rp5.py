"""Report content part 5: section 14 (AI/RAG/MCP)."""
from generate_report import S, P, bullets, table, Paragraph, W, mm, diag, d_rag

def build(s):
    def A(*items):
        for i in items:
            s.append(i)
    A(Paragraph("14. AI / LLM / RAG / MCP", S["H1"]))
    A(P("AI is the core of the product. The implementation is a disciplined RAG + multi-agent pipeline rather than "
        "a raw chat wrapper."))
    A(Paragraph("14.1 RAG Pipeline", S["H2"]))
    A(*diag(d_rag, 130, "Figure 3 - RAG indexing and retrieval flow for incident evidence"))
    A(table(["Aspect", "Implementation"], [
        ["LLM provider / model", "Google Gemini via google-genai SDK; model gemini-2.5-flash (default, configurable); timeout 60000 ms; 2 retries (3 attempts total)"],
        ["Embedding model", "SentenceTransformers BAAI/bge-small-en-v1.5, 384 dimensions, loaded once at module import"],
        ["Vector database", "Qdrant embedded local mode at backend/qdrant_data (QDRANT_PATH); collection enterprise_incidents; cosine distance"],
        ["Chunking strategy", "One vector per incident: 'Service / Title / Root Cause' text - a deliberate choice because incidents are small atomic records; no text chunking is applied"],
        ["Indexing", "scripts/seed.py validates required fields, embeds, upserts with deterministic UUIDv5 ids (safe to re-run), verifies stored count, exits non-zero on failure"],
        ["Retrieval", "Top-k cosine search (limit 5) with optional payload filters (service/severity/status); payload keyword indexes for filtered search"],
        ["Quality gate", "Results below MIN_RELEVANCE_SCORE (0.30) dropped before entering evidence; the strength heuristic additionally requires >= 0.45 for HIGH"],
        ["Context construction", "EvidenceBundle - formatted prompt sections with hard caps: 5 incidents, 5 deployments, 30 log lines, 3000 runbook chars - the raw log file is never dumped into the prompt"],
        ["Response generation", "Strict markdown template parsed back into InvestigationResult (summary, impact, root cause, lists, confidence)"],
        ["Guardrails", "Prompt forbids inventing data; confidence clamped by _final_confidence to the validator's strength; runbooks labelled guidance-only; timeline uses only real timestamps"],
        ["Fallbacks", "Gemini failure after retries - _fallback_result: evidence-only report, no root cause invented, explicit user message (verified live in this analysis)"],
    ], [30 * mm, W - 30 * mm]))
    A(Paragraph("14.2 Multi-Agent Design", S["H2"]))
    A(P("Four specialised retrieval agents (incident, deployment, log, runbook) plus a generation agent are "
        "coordinated by the LangGraph workflow. Each agent owns one data source and returns typed evidence, making "
        "the pipeline testable in isolation (tests/test_agents.py). This is a fixed orchestration graph, not an "
        "autonomous agent loop - deterministic, auditable and cheap."))
    A(Paragraph("14.3 MCP", S["H2"]))
    A(P("<b>Partially implemented.</b> backend/mcp_server/server.py defines a FastMCP server ('Enterprise RCA Tools') "
        "with four working tools that reuse the real service layer: search_incidents_tool, get_deployment, "
        "search_logs, get_runbook. It runs standalone (python -m mcp_server.server) and is intentionally not wired "
        "into the main API or consumed by any agent yet - the README lists it as future agent-integration surface."))
    A(Paragraph("14.4 Prompt Engineering Notes", S["H2"]))
    A(P("The RCA prompt embeds the user question, the validator's evidence strength, formatted incident/deployment/"
        "log/timeline sections and the runbook, then gives seven explicit instructions (use only the evidence; "
        "separate fact from inference; declare inconclusive when strength is LOW/INSUFFICIENT; treat runbooks as "
        "guidance; explain why the chosen root cause beats alternatives; state exactly one confidence level with "
        "justification and never claim High against low evidence strength). The markdown response is parsed with "
        "section extraction (_build_result) so the UI gets structured fields, not raw text."))
    return s