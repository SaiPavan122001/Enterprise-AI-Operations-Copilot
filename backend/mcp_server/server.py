from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Enterprise RCA Tools")


@mcp.tool()
def get_incidents():
    return "Incident tool working"


@mcp.tool()
def get_deployments():
    return "Deployment tool working"


@mcp.tool()
def get_logs():
    return "Log tool working"


if __name__ == "__main__":
    mcp.run()