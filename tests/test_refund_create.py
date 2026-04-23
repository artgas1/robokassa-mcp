"""Tests for refund_create: JWT construction and HTTP round-trip."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import jwt
import pytest

from robokassa import (
    PaymentMethod,
    PaymentObject,
    RefundInvoiceItem,
    RobokassaApiError,
    RobokassaClient,
    TaxType,
    build_refund_jwt,
    parse_refund_create_response,
    refund_create,
)

OP_KEY = "0005F891-8CCD-434B-8455-816AFFFDBF37-0VOisWikFF"
PASSWORD3 = "test_secret_password3"


def test_build_refund_jwt_minimal_full_refund() -> None:
    token = build_refund_jwt(op_key=OP_KEY, password3=PASSWORD3)
    decoded = jwt.decode(token, PASSWORD3, algorithms=["HS256"])
    assert decoded == {"OpKey": OP_KEY}


def test_build_refund_jwt_partial_refund_without_items() -> None:
    token = build_refund_jwt(op_key=OP_KEY, password3=PASSWORD3, refund_sum=Decimal("5.50"))
    decoded = jwt.decode(token, PASSWORD3, algorithms=["HS256"])
    assert decoded == {"OpKey": OP_KEY, "RefundSum": 5.5}


def test_build_refund_jwt_with_fiscal_receipt() -> None:
    items = [
        RefundInvoiceItem(
            name="Тестовый товар",
            quantity=1,
            cost=Decimal("1.00"),
            tax=TaxType.NONE,
            payment_method=PaymentMethod.FULL_PAYMENT,
            payment_object=PaymentObject.PAYMENT,
        ),
    ]
    token = build_refund_jwt(op_key=OP_KEY, password3=PASSWORD3, refund_sum=1.0, items=items)
    decoded = jwt.decode(token, PASSWORD3, algorithms=["HS256"])
    assert decoded["OpKey"] == OP_KEY
    assert decoded["RefundSum"] == 1.0
    assert decoded["InvoiceItems"] == [
        {
            "Name": "Тестовый товар",
            "Quantity": 1,
            "Cost": 1.0,
            "Tax": "none",
            "PaymentMethod": "full_payment",
            "PaymentObject": "payment",
        }
    ]


def test_build_refund_jwt_payload_is_compact_json() -> None:
    """Robokassa requires compact JSON — PyJWT defaults to it."""
    token = build_refund_jwt(op_key=OP_KEY, password3=PASSWORD3, refund_sum=1.0)
    payload_b64 = token.split(".")[1]
    # PyJWT strips b64 padding; re-add for urlsafe_b64decode.
    import base64

    padded = payload_b64 + "=" * ((4 - len(payload_b64) % 4) % 4)
    payload_text = base64.urlsafe_b64decode(padded).decode("utf-8")
    # Compact means no spaces between delimiters; re-serialize compact and compare.
    assert payload_text == json.dumps(json.loads(payload_text), separators=(",", ":"))


def test_build_refund_jwt_honors_algorithm() -> None:
    token = build_refund_jwt(op_key=OP_KEY, password3=PASSWORD3, algorithm="HS512")
    header_b64 = token.split(".")[0]
    import base64

    padded = header_b64 + "=" * ((4 - len(header_b64) % 4) % 4)
    header = json.loads(base64.urlsafe_b64decode(padded))
    assert header["alg"] == "HS512"


def test_parse_refund_create_response_success() -> None:
    result = parse_refund_create_response(
        {"success": True, "message": None, "requestId": "cf15fd52-d2d1-4fc4-b9c0-25310e3bdded"}
    )
    assert result.success is True
    assert result.request_id == "cf15fd52-d2d1-4fc4-b9c0-25310e3bdded"
    assert result.message is None
    assert result.is_success is True


def test_parse_refund_create_response_failure() -> None:
    result = parse_refund_create_response({"success": False, "message": "NotEnoughOperationFunds", "requestId": None})
    assert result.success is False
    assert result.request_id is None
    assert result.message == "NotEnoughOperationFunds"
    assert result.is_success is False


@pytest.mark.asyncio
async def test_refund_create_sends_jwt_and_returns_request_id() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers.get("Content-Type")
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={"success": True, "message": None, "requestId": "req-123"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await refund_create(OP_KEY, PASSWORD3, http_client=client)

    assert result.request_id == "req-123"
    assert captured["content_type"] == "application/jwt"
    assert "/Refund/Create" in str(captured["url"])
    # Verify the JWT is valid and contains OpKey.
    token = str(captured["body"])
    decoded = jwt.decode(token, PASSWORD3, algorithms=["HS256"])
    assert decoded["OpKey"] == OP_KEY


@pytest.mark.asyncio
async def test_refund_create_raises_on_api_failure_by_default() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"success": False, "message": "NotEnoughOperationFunds", "requestId": None},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RobokassaApiError, match="NotEnoughOperationFunds"):
            await refund_create(OP_KEY, PASSWORD3, http_client=client)


@pytest.mark.asyncio
async def test_refund_create_returns_error_when_suppressed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"success": False, "message": "AlreadyRefunded", "requestId": None},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await refund_create(OP_KEY, PASSWORD3, http_client=client, raise_on_api_error=False)

    assert result.success is False
    assert result.message == "AlreadyRefunded"


@pytest.mark.asyncio
async def test_client_refund_create_requires_password3() -> None:
    async with RobokassaClient("demo") as client:
        with pytest.raises(ValueError, match="password3"):
            await client.refund_create(OP_KEY)


@pytest.mark.asyncio
async def test_client_refund_create_delegates() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "message": None, "requestId": "abc"})

    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        client = RobokassaClient("demo", password3=PASSWORD3, http_client=transport_client)
        result = await client.refund_create(OP_KEY, refund_sum=Decimal("10.00"))
        assert result.request_id == "abc"
    finally:
        await transport_client.aclose()
