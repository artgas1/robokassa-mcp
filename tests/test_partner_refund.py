"""Tests for Partner API RefundOperation."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from robokassa import (
    RobokassaApiError,
    parse_partner_refund_response,
    partner_refund,
)

ROBOX_PARTNER_ID = "97b73dfc-58dd-4ec8-90b6-e1cac933f4f7"
OP_KEY = "A2180579-78EE-4E5C-957B-A5ED2C18A7B2-ffmLtLVZTm"


def test_parse_partner_refund_success() -> None:
    result = parse_partner_refund_response({"success": True, "error": "", "resultCode": 0})
    assert result.is_success is True
    assert result.error is None
    assert result.result_code == 0


def test_parse_partner_refund_failure() -> None:
    result = parse_partner_refund_response({"success": False, "error": "InvalidOpKey", "resultCode": 17})
    assert result.is_success is False
    assert result.error == "InvalidOpKey"
    assert result.result_code == 17


@pytest.mark.asyncio
async def test_partner_refund_posts_expected_payload_and_headers() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True, "error": "", "resultCode": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await partner_refund(
            robox_partner_id=ROBOX_PARTNER_ID,
            op_key=OP_KEY,
            auth_headers={"Authorization": "Bearer partner-jwt"},
            refund_sum=Decimal("5.00"),
            http_client=client,
        )

    assert result.is_success
    assert "/Operation/RefundOperation" in str(captured["url"])
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer partner-jwt"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["RoboxPartnerId"] == ROBOX_PARTNER_ID
    assert body["OpKey"] == OP_KEY
    assert body["RefundSum"] == 5.0


@pytest.mark.asyncio
async def test_partner_refund_raises_on_api_error_by_default() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "error": "NotEnoughFunds", "resultCode": 42})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RobokassaApiError, match="NotEnoughFunds"):
            await partner_refund(
                robox_partner_id=ROBOX_PARTNER_ID,
                op_key=OP_KEY,
                auth_headers={"Authorization": "Bearer x"},
                http_client=client,
            )


@pytest.mark.asyncio
async def test_partner_refund_suppresses_error_when_requested() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "error": "X", "resultCode": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await partner_refund(
            robox_partner_id=ROBOX_PARTNER_ID,
            op_key=OP_KEY,
            auth_headers={"Authorization": "Bearer x"},
            http_client=client,
            raise_on_api_error=False,
        )
    assert result.is_success is False
    assert result.error == "X"
