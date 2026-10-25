"""MCP server - LOCAL ONLY (stdio). Optional; not used by the API.

MCP has no authentication in this project, so the server:
* runs only over stdio (a local parent process); any other transport is refused;
* acts as a fixed low-privilege identity: role ``viewer`` in ``MCP_TENANT``
  (default "default"), able to read ONLY the services listed in
  ``MCP_SERVICES`` (comma-separated; empty = no record access - deny by default);
* exposes only read-only tools, through the same tool registry as the API
  (allowlist, schema validation, permission + resource checks, timeouts, audit);
  consequential tools are never exposed here.

Run:  MCP_SERVICES=payroll-service,auth-service python -m mcp_server.server
"""

import os
import sys

from mcp.server.fastmcp import FastMCP

from security import guardrails
from security.access import resolve_services
from security.principals import Principal
from tools import registry
from vector_store.search_service import search_incidents

mcp = FastMCP("Enterprise RCA Tools (local, read-only)")


def principal() -> Principal:
    tenant = os.getenv("MCP_TENANT", "default")
    grants = [s.strip() for s in os.getenv("MCP_SERVICES", "").split(",") if s.strip()]
    services = resolve_services(tenant, grants) if grants else frozenset()
    return Principal(name="mcp-local", role="viewer", tenant=tenant, services=services, method="mcp_stdio")


def _untrusted(result):
    """Record text returned to the MCP client's model is untrusted data: the same
    retrieval rail as the investigation pipeline neutralises instruction-like text."""
    if isinstance(result, dict):
        keys = [k for k, v in result.items() if isinstance(v, str)]
        cleaned, _ = guardrails.neutralize([result[k] for k in keys])
        return {**result, **dict(zip(keys, cleaned))}
    return result


def _call(name: str, args: dict) -> str:
    try:
        return str(_untrusted(registry.invoke(principal(), name, args)))
    except registry.ToolError as exc:
        return f"refused ({exc.code}): {exc.message}"


@mcp.tool()
def search_incidents_tool(query: str, limit: int = 5) -> str:
    """Semantic search over the incidents this local identity may read."""
    if not 2 <= len(query) <= 300 or not 1 <= limit <= 20:
        return "refused (invalid_arguments): query must be 2-300 characters and limit 1-20"
    p = principal()
    results = search_incidents(query=query, limit=limit, services=p.services)
    if not results:
        return "No relevant incidents found."
    lines = [f"{(r.payload or {}).get('incident_id')} [{(r.payload or {}).get('severity')}] "
             f"{(r.payload or {}).get('title')} (service={(r.payload or {}).get('service')}, "
             f"score={r.score:.2f})" for r in results]
    return "\n".join(guardrails.neutralize(lines)[0])


@mcp.tool()
def incident_lookup(incident_id: str) -> str:
    """Read one incident record (allowlisted registry tool)."""
    return _call("incident_lookup", {"incident_id": incident_id})


@mcp.tool()
def deployment_inspect(deployment_id: str) -> str:
    """Read one deployment record (allowlisted registry tool)."""
    return _call("deployment_inspect", {"deployment_id": deployment_id})


def main(argv=None) -> int:
    transport = (argv or sys.argv[1:] or ["stdio"])[0]
    if transport != "stdio":
        raise SystemExit("refused: the MCP server is local-only (stdio) until it has authentication")
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
