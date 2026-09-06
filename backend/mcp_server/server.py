"""MCP server exposing REAL investigation tools over the project's data
services. This is an isolated, optional integration (not used by the main
API yet) - kept for future agent integrations.

Run standalone with:  python -m mcp_server.server
"""

from mcp.server.fastmcp import FastMCP

from agents.log_agent import investigate_logs
from agents.runbook_agent import retrieve_runbook
from utils.data_store import get_deployments
from vector_store.search_service import search_incidents

mcp = FastMCP("Enterprise RCA Tools")


@mcp.tool()
def search_incidents_tool(query: str, limit: int = 5) -> str:
    """Semantic search over the enterprise incidents vector store."""
    results = search_incidents(query=query, limit=limit)
    if not results:
        return "No relevant incidents found."
    lines = []
    for point in results:
        p = point.payload or {}
        lines.append(
            f"{p.get('incident_id')} [{p.get('severity')}] "
            f"{p.get('title')} (service={p.get('service')}, score={point.score:.2f})"
        )
    return "\n".join(lines)


@mcp.tool()
def get_deployment(deployment_id: str) -> str:
    """Look up a single deployment by its exact ID."""
    for deployment in get_deployments():
        if deployment.get("deployment_id") == deployment_id:
            return str(deployment)
    return f"Deployment {deployment_id} not found."


@mcp.tool()
def search_logs(service: str) -> str:
    """Retrieve relevant log lines for a service (errors prioritised)."""
    class _Ref:
        pass

    ref = _Ref()
    ref.service = service
    entries = investigate_logs([ref])
    if not entries:
        return "No relevant log lines found."
    return "\n".join(
        f"{e.timestamp} {e.service} {e.level}: {e.message}" for e in entries[:20]
    )


@mcp.tool()
def get_runbook(question: str) -> str:
    """Retrieve the most relevant operational runbook for a question."""
    runbook = retrieve_runbook(question, [])
    if not runbook:
        return "No runbook matched the question."
    return f"Runbook: {runbook.title} (source: {runbook.name})\n{runbook.content}"


if __name__ == "__main__":
    mcp.run()
