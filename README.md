# robokassa-mcp

Python client and [Model Context Protocol](https://modelcontextprotocol.io) server for [Robokassa](https://robokassa.com) — the Russian payment gateway.

## Status

🚧 **Early development.** Not yet published. See [Linear project](https://linear.app/neirosova/project/robokassa-mcp-oss-ec1937aa7c65) for roadmap.

## Goals

- **Full API coverage.** All 8 groups of Robokassa API: checkout, XML interfaces, refunds, holding, recurring, fiscal receipts, partner API, auxiliary.
- **Two entry points.** A plain Python client (`robokassa`) for direct library use, and a thin FastMCP wrapper (`robokassa_mcp`) for AI agents.
- **Typed.** Full type hints, pyright strict mode.
- **MIT licensed.** Drop-and-forget maintenance — PRs welcome.

## Install (once published)

```bash
# As an MCP server
uvx robokassa-mcp

# As a Python library
pip install robokassa-mcp
```

## License

MIT
