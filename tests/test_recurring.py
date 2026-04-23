"""Tests for recurring parent + child charge."""

from __future__ import annotations

import hashlib
from decimal import Decimal

import httpx
import pytest

from robokassa import (
    RECURRING_URL,
    init_recurring_parent,
    recurring_charge,
)


def test_init_recurring_parent_adds_recurring_flag() -> None:
    invoice = init_recurring_parent(
        merchant_login="demo",
        out_sum="10.00",
        inv_id=154,
        password1="p1",
    )
    assert invoice.form_fields["Recurring"] == "true"
    # Recurring flag doesn't affect the signature — still the standard formula.
    expected = hashlib.md5(b"demo:10.00:154:p1").hexdigest()
    assert invoice.signature == expected


@pytest.mark.asyncio
async def test_recurring_charge_signature_excludes_previous_inv_id() -> None:
    """Signature is over the NEW invoice id only; Previous is in body only."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(RECURRING_URL)
        body = dict(httpx.QueryParams(request.content.decode()))
        captured.update(body)
        return httpx.Response(200, text="OK156")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await recurring_charge(
            merchant_login="demo",
            new_inv_id=156,
            previous_inv_id=154,
            out_sum=Decimal("10.00"),
            password1="p1",
            description="Subscription",
            http_client=client,
        )

    expected_sig = hashlib.md5(b"demo:10.00:156:p1").hexdigest()
    assert captured["SignatureValue"] == expected_sig
    assert captured["InvoiceID"] == "156"
    assert captured["PreviousInvoiceID"] == "154"
    assert captured["OutSum"] == "10.00"
    assert captured["Description"] == "Subscription"
    assert result.is_accepted is True
    assert result.body == "OK156"


@pytest.mark.asyncio
async def test_recurring_charge_with_receipt_includes_receipt_in_signature() -> None:
    from robokassa import CheckoutReceipt, CheckoutReceiptItem

    receipt = CheckoutReceipt(items=[CheckoutReceiptItem(name="Sub", quantity=1, sum=Decimal("10.00"))])
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(request.content.decode()))
        captured.update(body)
        return httpx.Response(200, text="OK200")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await recurring_charge(
            merchant_login="demo",
            new_inv_id=200,
            previous_inv_id=154,
            out_sum="10.00",
            password1="p1",
            receipt=receipt,
            http_client=client,
        )

    receipt_json = receipt.to_json()
    expected = hashlib.md5(f"demo:10.00:200:{receipt_json}:p1".encode()).hexdigest()
    assert captured["SignatureValue"] == expected


@pytest.mark.asyncio
async def test_recurring_charge_is_accepted_recognizes_non_ok_body() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Error 3: Operation not found")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await recurring_charge(
            merchant_login="demo",
            new_inv_id=1,
            previous_inv_id=0,
            out_sum="1.00",
            password1="p1",
            http_client=client,
        )
    assert result.is_accepted is False
