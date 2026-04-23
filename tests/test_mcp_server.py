"""Smoke tests for the FastMCP server — ensure all tools are registered."""

from __future__ import annotations

import pytest

EXPECTED_TOOLS = {
    "check_payment",
    "create_invoice",
    "list_currencies",
    "calc_out_sum",
    "refund_create",
    "refund_status",
    "verify_result_signature",
    "verify_success_signature",
    "hold_init",
    "hold_confirm",
    "hold_cancel",
    "init_recurring_parent",
    "recurring_charge",
    "build_split_invoice",
    "send_sms",
    "second_receipt_create",
    "second_receipt_status",
    "partner_refund",
}


@pytest.mark.asyncio
async def test_all_expected_tools_registered() -> None:
    """FastMCP should expose every tool from the library surface."""
    from robokassa_mcp.server import mcp

    tools = await mcp.list_tools()
    registered = {t.name for t in tools}
    missing = EXPECTED_TOOLS - registered
    assert not missing, f"Missing MCP tools: {sorted(missing)}"


@pytest.mark.asyncio
async def test_every_tool_has_a_description() -> None:
    """Every @mcp.tool() should carry a description for the LLM."""
    from robokassa_mcp.server import mcp

    tools = await mcp.list_tools()
    missing_desc = [t.name for t in tools if not t.description]
    assert not missing_desc, f"Tools without description: {missing_desc}"
