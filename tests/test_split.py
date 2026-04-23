"""Tests for split payment URL builder."""

from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from robokassa import SplitRecipient, build_split_invoice


def test_build_split_invoice_embeds_splits_in_json() -> None:
    invoice = build_split_invoice(
        out_amount=Decimal("700.00"),
        splits=[
            SplitRecipient(merchant_login="shop1", amount=Decimal("500.00")),
            SplitRecipient(merchant_login="shop2", amount=Decimal("200.00")),
        ],
        email="buyer@example.com",
        inc_curr="BankCard",
    )
    payload = json.loads(invoice.invoice_json)
    assert payload["outAmount"] == 700.0
    assert payload["email"] == "buyer@example.com"
    assert payload["incCurr"] == "BankCard"
    assert [s["merchantLogin"] for s in payload["splits"]] == ["shop1", "shop2"]
    assert [s["amount"] for s in payload["splits"]] == [500.0, 200.0]


def test_build_split_invoice_produces_valid_url_with_encoded_json() -> None:
    invoice = build_split_invoice(
        out_amount=100,
        splits=[SplitRecipient(merchant_login="shop1", amount=100)],
    )
    parsed = urlparse(invoice.url)
    assert parsed.path.endswith("/CreateV2")
    query = parse_qs(parsed.query)
    assert "invoice" in query
    # The invoice param should round-trip through JSON decode.
    reparsed = json.loads(query["invoice"][0])
    assert reparsed["outAmount"] == 100.0


def test_build_split_invoice_rejects_mismatched_total() -> None:
    with pytest.raises(ValueError, match="splits sum"):
        build_split_invoice(
            out_amount=Decimal("100"),
            splits=[SplitRecipient(merchant_login="shop1", amount=Decimal("90"))],
        )


def test_build_split_invoice_rejects_empty_splits() -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_split_invoice(out_amount=100, splits=[])


def test_build_split_invoice_includes_per_split_description() -> None:
    invoice = build_split_invoice(
        out_amount=10,
        splits=[
            SplitRecipient(merchant_login="shop1", amount=10, description="Product A seller"),
        ],
    )
    payload = json.loads(invoice.invoice_json)
    assert payload["splits"][0]["description"] == "Product A seller"
