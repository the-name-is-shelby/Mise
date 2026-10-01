from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mise")

@mcp.tool()
def ping() -> str:
    """Health check."""
    return "mise is alive"

if __name__ == "__main__":
    mcp.run(transport="streamable-http")