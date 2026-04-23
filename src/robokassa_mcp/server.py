"""FastMCP server exposing Robokassa tools to AI agents."""

from fastmcp import FastMCP

mcp: FastMCP = FastMCP("robokassa")


def main() -> None:
    """Entry point for the `robokassa-mcp` console script."""
    mcp.run()


if __name__ == "__main__":
    main()
