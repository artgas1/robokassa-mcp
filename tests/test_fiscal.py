"""Tests for fiscal (54-ФЗ) second receipts."""

from __future__ import annotations

import base64
import hashlib
import json

import httpx
import pytest

from robokassa import (
    encode_fiscal_body,
    second_receipt_create,
    second_receipt_status,
)


def test_encode_fiscal_body_format() -> None:
    """Body is `<b64(json)>.<b64(md5(json+p1))>` with no base64 padding."""
    payload = {"merchantId": "robokassa_sell", "id": "14"}
    body = encode_fiscal_body(payload, "p1")

    b64_json, b64_sig = body.split(".")
    # Neither segment should have `=` padding.
    assert "=" not in b64_json
    assert "=" not in b64_sig

    # Re-add padding and decode to confirm contents.
    def pad(s: str) -> str:
        return s + "=" * ((4 - len(s) % 4) % 4)

    decoded_json = base64.b64decode(pad(b64_json)).decode("utf-8")
    assert json.loads(decoded_json) == payload
    # Compact JSON — should match re-serialized compact form.
    assert decoded_json == json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    expected_sig = hashlib.md5(decoded_json.encode() + b"p1").hexdigest()
    decoded_sig = base64.b64decode(pad(b64_sig)).decode("utf-8")
    assert decoded_sig == expected_sig


@pytest.mark.asyncio
async def test_second_receipt_create_posts_encoded_body() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/Receipt/Attach" in str(request.url)
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json={"ResultCode": "0", "ResultDescription": "ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await second_receipt_create(
            merchant_id="robokassa_sell",
            receipt_id="14",
            origin_id="13",
            items=[
                {
                    "name": "Тест",
                    "quantity": 1,
                    "sum": 100,
                    "tax": "none",
                    "payment_method": "full_payment",
                    "payment_object": "commodity",
                }
            ],
            total=100,
            client={"email": "x@y.ru"},
            payments=[{"type": 2, "sum": 100}],
            password1="p1",
            sno="osn",
            url="https://shop.example.com",
            http_client=client,
        )

    assert result.result_code == "0"
    assert result.result_description == "ok"
    # Body should have the "b64.b64" shape.
    assert "." in captured["body"]


@pytest.mark.asyncio
async def test_second_receipt_status_returns_fiscal_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/Receipt/Status" in str(request.url)
        return httpx.Response(
            200,
            json={
                "Code": "2",
                "Description": "Done",
                "FnNumber": "9289000100348548",
                "FiscalDocumentNumber": "135771",
                "FiscalDocumentAttribute": "207899681",
                "FiscalDate": None,
                "FiscalType": None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await second_receipt_status(
            merchant_id="robokassa_state",
            receipt_id="14",
            password1="p1",
            http_client=client,
        )

    assert result.code == "2"
    assert result.description == "Done"
    assert result.fn_number == "9289000100348548"
    assert result.fiscal_document_number == "135771"
    assert result.fiscal_document_attribute == "207899681"
