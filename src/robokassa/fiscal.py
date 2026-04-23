"""Robokassa fiscal receipts (54-ФЗ) — second-receipt formation.

Endpoints:
    - POST https://ws.roboxchange.com/RoboFiscal/Receipt/Attach
    - POST https://ws.roboxchange.com/RoboFiscal/Receipt/Status

Each endpoint accepts a specially-encoded body:

    <base64(json_body)>.<base64(md5(json_body + Password1))>

(Both base64 segments are unpadded — trailing `=` is stripped.)

This is used when the initial payment was made as an advance/prepayment
(`payment_method` = `advance` / `full_prepayment` / `partial_prepayment`)
and the shop needs to emit a final receipt with `payment_method=full_payment`
after goods are delivered. Max two receipts per operation.

Only available to merchants using Robokassa Fiscal.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final

import httpx

from robokassa.types import RobokassaResponseError

FISCAL_BASE_URL: Final[str] = "https://ws.roboxchange.com/RoboFiscal"


@dataclass(frozen=True, slots=True)
class FiscalAttachResult:
    """Response from POST /Receipt/Attach."""

    result_code: str
    result_description: str | None = None


@dataclass(frozen=True, slots=True)
class FiscalStatusResult:
    """Response from POST /Receipt/Status."""

    code: str
    description: str | None = None
    fn_number: str | None = None
    fiscal_document_number: str | None = None
    fiscal_document_attribute: str | None = None
    fiscal_date: str | None = None
    fiscal_type: str | None = None


def _b64_no_padding(data: bytes) -> str:
    """Robokassa fiscal wants base64 without `=` padding."""
    return base64.b64encode(data).decode("ascii").rstrip("=")


def encode_fiscal_body(payload: dict[str, Any], password1: str) -> str:
    """Build the `<b64(json)>.<b64(md5(json+p1))>` body used by RoboFiscal.

    The JSON is compact (no whitespace between separators).
    """
    json_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = hashlib.md5(json_bytes + password1.encode("utf-8")).hexdigest()
    return f"{_b64_no_padding(json_bytes)}.{_b64_no_padding(signature.encode('utf-8'))}"


def _parse_json_body(response: httpx.Response) -> dict[str, Any]:
    try:
        data: Any = response.json()
    except ValueError as exc:
        raise RobokassaResponseError(f"Non-JSON fiscal response: {response.text!r}") from exc
    if not isinstance(data, dict):
        raise RobokassaResponseError(f"Unexpected fiscal response shape: {data!r}")
    return data  # type: ignore[no-any-return]


async def second_receipt_create(
    *,
    merchant_id: str,
    receipt_id: str,
    origin_id: str,
    items: list[dict[str, Any]],
    total: float,
    client: dict[str, str],
    payments: list[dict[str, Any]],
    password1: str,
    operation: str = "sell",
    sno: str | None = None,
    url: str | None = None,
    vats: list[dict[str, Any]] | None = None,
    base_url: str = FISCAL_BASE_URL,
    http_client: httpx.AsyncClient | None = None,
) -> FiscalAttachResult:
    """Emit a final (second) fiscal receipt for a prior advance/prepayment.

    Args:
        merchant_id: Merchant ID in Robokassa Fiscal (e.g. `robokassa_sell`).
        receipt_id: New unique id for this receipt (distinct from origin_id).
        origin_id: InvId of the original operation that already has a receipt.
        items: Line items. Each: `{name, quantity, sum, tax, payment_method,
            payment_object, nomenclature_code}`. For the final receipt,
            `payment_method` must be `full_payment`.
        total: Total amount in rubles.
        client: `{email}` or `{phone}` — at least one required.
        payments: Payment breakdown. For offsetting a prepayment use
            `[{"type": 2, "sum": <total>}]`.
        password1: Merchant Password#1.
        operation: Always `sell` for final receipts.
        sno: Taxation scheme (`osn` / `usn_income` / ...).
        url: Site URL where the sale occurred (required by Robokassa).
        vats: Optional VAT breakdown.

    Returns:
        `FiscalAttachResult` with ResultCode:
            '0' — ok / ожидание регистрации
            '1' — ожидание регистрации
            '2' — чек зарегистрирован
            '3' — ошибка регистрации
            '1000' — внутренняя ошибка
    """
    payload: dict[str, Any] = {
        "merchantId": merchant_id,
        "id": receipt_id,
        "originId": origin_id,
        "operation": operation,
        "total": total,
        "items": items,
        "client": client,
        "payments": payments,
    }
    if sno is not None:
        payload["sno"] = sno
    if url is not None:
        payload["url"] = url
    if vats is not None:
        payload["vats"] = vats

    body = encode_fiscal_body(payload, password1)
    endpoint = f"{base_url}/Receipt/Attach"

    owns_client = http_client is None
    http = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await http.post(endpoint, content=body, headers={"Content-Type": "text/plain"})
        response.raise_for_status()
        data = _parse_json_body(response)
    finally:
        if owns_client:
            await http.aclose()

    return FiscalAttachResult(
        result_code=str(data.get("ResultCode", "")),
        result_description=data.get("ResultDescription"),
    )


async def second_receipt_status(
    *,
    merchant_id: str,
    receipt_id: str,
    password1: str,
    base_url: str = FISCAL_BASE_URL,
    http_client: httpx.AsyncClient | None = None,
) -> FiscalStatusResult:
    """Check the registration status of a previously-created fiscal receipt.

    Args:
        merchant_id: Status lookup uses a dedicated merchantId
            (`robokassa_state`).
        receipt_id: The id used when creating the receipt.
        password1: Merchant Password#1.
    """
    payload: dict[str, Any] = {"merchantId": merchant_id, "id": receipt_id}
    body = encode_fiscal_body(payload, password1)
    endpoint = f"{base_url}/Receipt/Status"

    owns_client = http_client is None
    http = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await http.post(endpoint, content=body, headers={"Content-Type": "text/plain"})
        response.raise_for_status()
        data = _parse_json_body(response)
    finally:
        if owns_client:
            await http.aclose()

    return FiscalStatusResult(
        code=str(data.get("Code", "")),
        description=data.get("Description"),
        fn_number=data.get("FnNumber"),
        fiscal_document_number=data.get("FiscalDocumentNumber"),
        fiscal_document_attribute=data.get("FiscalDocumentAttribute"),
        fiscal_date=data.get("FiscalDate"),
        fiscal_type=data.get("FiscalType"),
    )


__all__ = [
    "FISCAL_BASE_URL",
    "FiscalAttachResult",
    "FiscalStatusResult",
    "encode_fiscal_body",
    "second_receipt_create",
    "second_receipt_status",
]
