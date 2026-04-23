"""Tests for create_invoice checkout URL + signature construction."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from robokassa import (
    CheckoutReceipt,
    CheckoutReceiptItem,
    PaymentMethod,
    PaymentObject,
    TaxType,
    build_checkout_signature,
    create_invoice,
)


def test_signature_matches_docs_php_example() -> None:
    """Matches the vector from docs.robokassa.ru/code-examples (PHP example).

    PHP: md5("demo:5.12:5:securepass1")
    """
    expected = hashlib.md5(b"demo:5.12:5:securepass1").hexdigest()
    assert (
        build_checkout_signature(
            merchant_login="demo",
            out_sum="5.12",
            inv_id=5,
            password1="securepass1",
        )
        == expected
    )


def test_signature_with_receipt_puts_receipt_before_password() -> None:
    receipt_json = '{"items":[]}'
    expected = hashlib.md5(b"demo:5.12:5:" + receipt_json.encode() + b":securepass1").hexdigest()
    assert (
        build_checkout_signature(
            merchant_login="demo",
            out_sum="5.12",
            inv_id=5,
            password1="securepass1",
            receipt_json=receipt_json,
        )
        == expected
    )


def test_signature_appends_shp_params_alphabetically() -> None:
    """Shp_* params follow the password in alphabetical order."""
    expected = hashlib.md5(b"demo:5.12:5:securepass1:Shp_a=1:Shp_b=2").hexdigest()
    assert (
        build_checkout_signature(
            merchant_login="demo",
            out_sum="5.12",
            inv_id=5,
            password1="securepass1",
            shp_params={"Shp_b": "2", "Shp_a": "1"},
        )
        == expected
    )


def test_signature_respects_algorithm() -> None:
    md5 = build_checkout_signature(
        merchant_login="demo",
        out_sum="1.00",
        inv_id=1,
        password1="p1",
        algorithm="md5",
    )
    sha256 = build_checkout_signature(
        merchant_login="demo",
        out_sum="1.00",
        inv_id=1,
        password1="p1",
        algorithm="sha256",
    )
    assert len(md5) == 32
    assert len(sha256) == 64


def test_create_invoice_formats_out_sum_to_two_decimal_places() -> None:
    """Robokassa expects OutSum with exactly 2 decimal places."""
    invoice = create_invoice(
        merchant_login="demo",
        out_sum=5,  # int
        inv_id=1,
        password1="p1",
    )
    assert invoice.form_fields["OutSum"] == "5.00"

    invoice2 = create_invoice(
        merchant_login="demo",
        out_sum=Decimal("5.123"),
        inv_id=1,
        password1="p1",
    )
    assert invoice2.form_fields["OutSum"] == "5.12"


def test_create_invoice_url_has_all_required_query_params() -> None:
    invoice = create_invoice(
        merchant_login="demo",
        out_sum="5.12",
        inv_id=5,
        password1="p1",
        description="Order #5",
        email="user@example.com",
        is_test=True,
    )
    parsed = urlparse(invoice.url)
    query = parse_qs(parsed.query)
    assert query["MerchantLogin"] == ["demo"]
    assert query["OutSum"] == ["5.12"]
    assert query["InvId"] == ["5"]
    assert query["Description"] == ["Order #5"]
    assert query["Email"] == ["user@example.com"]
    assert query["IsTest"] == ["1"]
    assert "SignatureValue" in query
    # Culture defaults to 'ru'.
    assert query["Culture"] == ["ru"]


def test_create_invoice_prefixes_shp_keys_automatically() -> None:
    """Callers can pass `order_id` and we'll add `Shp_` prefix."""
    invoice = create_invoice(
        merchant_login="demo",
        out_sum="1.00",
        inv_id=1,
        password1="p1",
        shp_params={"order_id": "42"},
    )
    assert invoice.form_fields["Shp_order_id"] == "42"
    # Prefix should not be doubled.
    invoice2 = create_invoice(
        merchant_login="demo",
        out_sum="1.00",
        inv_id=1,
        password1="p1",
        shp_params={"Shp_order_id": "42"},
    )
    assert invoice2.form_fields["Shp_order_id"] == "42"
    assert "Shp_Shp_order_id" not in invoice2.form_fields


def test_create_invoice_with_fiscal_receipt() -> None:
    receipt = CheckoutReceipt(
        items=[
            CheckoutReceiptItem(
                name="Тестовый товар",
                quantity=1,
                sum=Decimal("5.12"),
                tax=TaxType.NONE,
                payment_method=PaymentMethod.FULL_PAYMENT,
                payment_object=PaymentObject.COMMODITY,
            ),
        ],
        sno="osn",
    )
    invoice = create_invoice(
        merchant_login="demo",
        out_sum="5.12",
        inv_id=5,
        password1="p1",
        receipt=receipt,
    )
    assert invoice.receipt_json is not None
    assert '"items"' in invoice.receipt_json
    assert "sno" in invoice.receipt_json
    # Receipt_json should have participated in signature — verify by recomputing.
    expected_sig = build_checkout_signature(
        merchant_login="demo",
        out_sum="5.12",
        inv_id=5,
        password1="p1",
        receipt_json=invoice.receipt_json,
    )
    assert invoice.signature == expected_sig


def test_create_invoice_signature_matches_manual_formula() -> None:
    invoice = create_invoice(
        merchant_login="demo",
        out_sum="5.12",
        inv_id=5,
        password1="securepass1",
    )
    expected = hashlib.md5(b"demo:5.12:5:securepass1").hexdigest()
    assert invoice.signature == expected
    assert invoice.form_fields["SignatureValue"] == expected


@pytest.mark.parametrize(
    "algorithm,length",
    [("md5", 32), ("sha256", 64), ("sha384", 96), ("sha512", 128)],
)
def test_create_invoice_supports_all_signature_algorithms(algorithm: str, length: int) -> None:
    invoice = create_invoice(
        merchant_login="demo",
        out_sum="1.00",
        inv_id=1,
        password1="p1",
        algorithm=algorithm,  # type: ignore[arg-type]
    )
    assert len(invoice.signature) == length
