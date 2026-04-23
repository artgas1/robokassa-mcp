"""Tests for hold_init / hold_confirm / hold_cancel."""

from __future__ import annotations

import hashlib
from decimal import Decimal

import httpx
import pytest

from robokassa import (
    HOLD_CANCEL_URL,
    HOLD_CONFIRM_URL,
    hold_cancel,
    hold_confirm,
    hold_init,
)


def test_hold_init_signature_includes_true_before_password() -> None:
    """Formula: MerchantLogin:OutSum:InvoiceId:true:Password#1 (no receipt)."""
    invoice = hold_init(
        merchant_login="demo",
        out_sum="1.00",
        inv_id=1570,
        password1="p1",
    )
    expected = hashlib.md5(b"demo:1.00:1570:true:p1").hexdigest()
    assert invoice.signature == expected
    assert invoice.form_fields["StepByStep"] == "true"
    assert invoice.form_fields["SignatureValue"] == expected


def test_hold_init_signature_with_receipt_has_true_after_receipt() -> None:
    """Formula with receipt: MerchantLogin:OutSum:InvoiceId:Receipt:true:Password#1."""
    from robokassa import CheckoutReceipt, CheckoutReceiptItem

    receipt = CheckoutReceipt(items=[CheckoutReceiptItem(name="x", quantity=1, sum=Decimal("1.00"))])
    invoice = hold_init(
        merchant_login="demo",
        out_sum="1.00",
        inv_id=1570,
        password1="p1",
        receipt=receipt,
    )
    receipt_json = receipt.to_json()
    raw = f"demo:1.00:1570:{receipt_json}:true:p1".encode()
    assert invoice.signature == hashlib.md5(raw).hexdigest()


@pytest.mark.asyncio
async def test_hold_confirm_signature_without_receipt() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(HOLD_CONFIRM_URL)
        body = dict(httpx.QueryParams(request.content.decode()))
        captured.update(body)
        return httpx.Response(200, text="")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await hold_confirm(
            merchant_login="demo",
            out_sum="1.00",
            inv_id=1570,
            password1="p1",
            http_client=client,
        )

    expected = hashlib.md5(b"demo:1.00:1570:p1").hexdigest()
    assert captured["SignatureValue"] == expected
    assert captured["OutSum"] == "1.00"
    assert captured["InvoiceID"] == "1570"


@pytest.mark.asyncio
async def test_hold_confirm_signature_with_receipt() -> None:
    from robokassa import CheckoutReceipt, CheckoutReceiptItem

    receipt = CheckoutReceipt(items=[CheckoutReceiptItem(name="x", quantity=1, sum=Decimal("1.00"))])
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(request.content.decode()))
        captured.update(body)
        return httpx.Response(200, text="")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await hold_confirm(
            merchant_login="demo",
            out_sum="1.00",
            inv_id=1570,
            password1="p1",
            receipt=receipt,
            http_client=client,
        )

    receipt_json = receipt.to_json()
    raw = f"demo:1.00:1570:{receipt_json}:p1".encode()
    assert captured["SignatureValue"] == hashlib.md5(raw).hexdigest()


@pytest.mark.asyncio
async def test_hold_cancel_signature_has_empty_outsum_slot() -> None:
    """Formula: MerchantLogin::InvoiceId:Password#1 — literal double colon."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(HOLD_CANCEL_URL)
        body = dict(httpx.QueryParams(request.content.decode()))
        captured.update(body)
        return httpx.Response(200, text="")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await hold_cancel(
            merchant_login="demo",
            inv_id=1570,
            password1="p1",
            http_client=client,
        )

    expected = hashlib.md5(b"demo::1570:p1").hexdigest()
    assert captured["SignatureValue"] == expected
    assert "OutSum" not in captured  # body doesn't include OutSum for cancel
