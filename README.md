<!-- mcp-name: io.github.artgas1/robokassa-mcp -->

<p align="center">
  <img src="https://raw.githubusercontent.com/artgas1/robokassa-mcp/main/.github/hero.svg" alt="robokassa-mcp — Robokassa payment gateway exposed to AI agents through MCP" width="820"/>
</p>

<h1 align="center">robokassa-mcp</h1>

<p align="center">
  <a href="https://github.com/artgas1/robokassa-mcp/actions/workflows/ci.yml"><img src="https://github.com/artgas1/robokassa-mcp/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <a href="https://pypi.org/project/robokassa-mcp/"><img src="https://img.shields.io/pypi/v/robokassa-mcp.svg" alt="PyPI"/></a>
  <a href="https://pypi.org/project/robokassa-mcp/"><img src="https://img.shields.io/pypi/pyversions/robokassa-mcp.svg" alt="Python"/></a>
  <a href="./LICENSE"><img src="https://img.shields.io/pypi/l/robokassa-mcp.svg" alt="License"/></a>
  <a href="https://ag-ae4b3bf7.mintlify.app"><img src="https://img.shields.io/badge/docs-mintlify-0068FF.svg" alt="Docs"/></a>
</p>

<p align="center">
  <b>📚 <a href="https://ag-ae4b3bf7.mintlify.app">Documentation</a></b> &nbsp;·&nbsp;
  <a href="https://pypi.org/project/robokassa-mcp/">PyPI</a> &nbsp;·&nbsp;
  <a href="https://github.com/artgas1/robokassa-mcp/pkgs/container/robokassa-mcp">Docker</a> &nbsp;·&nbsp;
  <a href="https://registry.modelcontextprotocol.io/v0/servers?search=robokassa">MCP Registry</a>
</p>

---

Comprehensive Python client and [Model Context Protocol](https://modelcontextprotocol.io) server for [Robokassa](https://robokassa.com) — the Russian payment gateway.

Covers the full API surface: checkout, XML status interfaces, refunds, holding (pre-auth), recurring subscriptions, 54-ФЗ fiscal receipts, Partner API, and auxiliary endpoints.

## Install (once published)

```bash
# As an MCP server for Claude Desktop / Claude Code / Cursor / Windsurf
uvx robokassa-mcp

# As a Python library
pip install robokassa-mcp
```

## Use as a Python library

```python
import asyncio
from decimal import Decimal
from robokassa import create_invoice, RobokassaClient

# Build a signed checkout URL (no HTTP — just URL construction).
invoice = create_invoice(
    merchant_login="my-shop",
    out_sum=Decimal("599.00"),
    inv_id=12345,
    password1="...",
    description="Premium subscription",
    email="user@example.com",
)
print(invoice.url)  # https://auth.robokassa.ru/Merchant/Index.aspx?...

# Check the state of a payment (hits the OpStateExt XML endpoint).
async def check() -> None:
    async with RobokassaClient("my-shop", password2="...") as client:
        state = await client.check_payment(inv_id=12345)
        print(state.is_paid, state.info.op_key)

asyncio.run(check())
```

### Full refund flow

```python
from robokassa import RobokassaClient

async def refund_flow(inv_id: int) -> None:
    async with RobokassaClient("my-shop", password2="p2", password3="p3") as client:
        # 1. Fetch the payment state to get its OpKey.
        state = await client.check_payment(inv_id)
        assert state.info.op_key, "payment not complete yet"

        # 2. Initiate a refund.
        created = await client.refund_create(state.info.op_key)
        print("refund requestId:", created.request_id)

        # 3. Poll status until finished / canceled.
        while True:
            status = await client.refund_status(created.request_id)
            if status.is_terminal:
                print("final:", status.state)
                break
```

### Webhook signature verification (FastAPI example)

```python
from fastapi import FastAPI, Request, HTTPException, PlainTextResponse
from robokassa import verify_result_signature, build_ok_response

app = FastAPI()

@app.post("/robokassa/result")
async def result_url(req: Request) -> PlainTextResponse:
    form = dict(await req.form())
    if not verify_result_signature(form, password2="..."):
        raise HTTPException(status_code=403, detail="Bad signature")
    # ... persist the notification, mark invoice paid ...
    return PlainTextResponse(build_ok_response(form["InvId"]))
```

## Use as an MCP server

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "robokassa": {
      "command": "uvx",
      "args": ["robokassa-mcp"],
      "env": {
        "ROBOKASSA_LOGIN": "your-shop-login",
        "ROBOKASSA_PASSWORD1": "password1",
        "ROBOKASSA_PASSWORD2": "password2",
        "ROBOKASSA_PASSWORD3": "password3"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add robokassa \
  -e ROBOKASSA_LOGIN=my-shop \
  -e ROBOKASSA_PASSWORD1=... \
  -e ROBOKASSA_PASSWORD2=... \
  -e ROBOKASSA_PASSWORD3=... \
  -- uvx robokassa-mcp
```

### Cursor

Edit `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "robokassa": {
      "command": "uvx",
      "args": ["robokassa-mcp"],
      "env": {
        "ROBOKASSA_LOGIN": "your-shop-login",
        "ROBOKASSA_PASSWORD1": "password1",
        "ROBOKASSA_PASSWORD2": "password2",
        "ROBOKASSA_PASSWORD3": "password3"
      }
    }
  }
}
```

### VS Code (GitHub Copilot)

In user or workspace `settings.json`:

```json
{
  "github.copilot.chat.mcp.servers": {
    "robokassa": {
      "command": "uvx",
      "args": ["robokassa-mcp"],
      "env": {
        "ROBOKASSA_LOGIN": "your-shop-login",
        "ROBOKASSA_PASSWORD1": "password1",
        "ROBOKASSA_PASSWORD2": "password2",
        "ROBOKASSA_PASSWORD3": "password3"
      }
    }
  }
}
```

### Windsurf

Edit `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "robokassa": {
      "command": "uvx",
      "args": ["robokassa-mcp"],
      "env": {
        "ROBOKASSA_LOGIN": "your-shop-login",
        "ROBOKASSA_PASSWORD1": "password1",
        "ROBOKASSA_PASSWORD2": "password2",
        "ROBOKASSA_PASSWORD3": "password3"
      }
    }
  }
}
```

### HTTP transport (MCP Inspector, remote clients)

```bash
uvx robokassa-mcp --transport http --port 8000
```

Flags: `--transport {stdio,http,streamable-http,sse}`, `--host`, `--port`.

## MCP tools exposed to agents

All 18 tools are wrapped as `@mcp.tool()` and available to any MCP-capable agent (Claude Desktop, Claude Code, Cursor, Windsurf, etc.).

| Tool | Purpose | Auth |
|---|---|---|
| `create_invoice` | Build a signed checkout URL (optional 54-ФЗ receipt). | Password#1 |
| `check_payment` | Get current state of a payment by InvId (via OpStateExt). | Password#2 |
| `list_currencies` | List payment methods available to the shop. | — |
| `calc_out_sum` | Compute amount credited to shop for a given payment. | Password#1 |
| `refund_create` | Initiate a refund (requires Refund API access). | Password#3 JWT |
| `refund_status` | Poll refund progress by requestId. | — |
| `verify_result_signature` | Validate a ResultURL webhook. | Password#2 |
| `verify_success_signature` | Validate a SuccessURL redirect. | Password#1 |
| `hold_init` / `hold_confirm` / `hold_cancel` | Two-step card pre-authorization. | Password#1 |
| `init_recurring_parent` / `recurring_charge` | Subscription auto-charges. | Password#1 |
| `build_split_invoice` | Marketplace multi-recipient checkout. | — |
| `send_sms` | Paid SMS service. | Password#1 |
| `second_receipt_create` / `second_receipt_status` | 54-ФЗ final receipt after advance. | Password#1 |
| `partner_refund` | Alternative refund path for partner integrators. | Partner JWT |

Low-level signature helpers are available from Python only: `compute_signature`, `op_state_signature`, `build_checkout_signature`, `build_refund_jwt`, `build_sms_signature`, `compute_result_signature`, `compute_success_signature`, `encode_fiscal_body`.

## API coverage

Mapped against the 8 public Robokassa API groups:

| Group | Coverage | Module |
|---|---|---|
| Merchant Checkout | ✅ `create_invoice` (+ 54-ФЗ) | `robokassa.checkout` |
| XML Interfaces | ✅ `check_payment`, `list_currencies`, `calc_out_sum` | `robokassa.xml_interface` |
| Refund API | ✅ `refund_create`, `refund_status` | `robokassa.refund` |
| Holding / Pre-auth | ✅ init / confirm / cancel | `robokassa.holding` |
| Recurring | ✅ parent + child | `robokassa.recurring` |
| Fiscal 54-ФЗ | ✅ second receipt create / status | `robokassa.fiscal` |
| Partner API | 🟡 `partner_refund` only — [see coverage notes](./docs/partner-api.md) | `robokassa.partner` |
| Auxiliary | ✅ `send_sms`, webhook signatures, split payments | `robokassa.sms`, `robokassa.webhooks`, `robokassa.split` |

## Environment variables

Most high-level entry points fall back to these env vars when credentials aren't passed explicitly:

| Variable | Required for |
|---|---|
| `ROBOKASSA_LOGIN` | All operations |
| `ROBOKASSA_PASSWORD1` | Checkout, webhook SuccessURL verification, CalcOutSumm, fiscal, SMS |
| `ROBOKASSA_PASSWORD2` | `check_payment` (OpStateExt), webhook ResultURL verification |
| `ROBOKASSA_PASSWORD3` | `refund_create` |

## Signature algorithms

All signature-producing helpers accept `algorithm=` with `"md5" / "sha256" / "sha384" / "sha512"` — match whatever is configured in your Robokassa cabinet.

## Development

```bash
git clone https://github.com/artgas1/robokassa-mcp.git
cd robokassa-mcp
uv sync --all-extras --dev
uv run pytest            # 107+ unit tests
uv run ruff check .
uv run pyright
```

## License

MIT — see [LICENSE](./LICENSE). Drop-and-forget maintenance; PRs welcome but not guaranteed to be reviewed promptly.
