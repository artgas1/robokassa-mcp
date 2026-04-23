"""FastMCP server exposing Robokassa tools to AI agents."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from fastmcp import FastMCP

from robokassa import check_payment as _check_payment
from robokassa import create_invoice as _create_invoice
from robokassa import refund_create as _refund_create
from robokassa import refund_status as _refund_status
from robokassa.checkout import CheckoutReceipt, CheckoutReceiptItem
from robokassa.refund import JwtAlgorithm, PaymentMethod, PaymentObject, RefundInvoiceItem, TaxType
from robokassa.signatures import SignatureAlgorithm
from robokassa.webhooks import (
    build_ok_response as _build_ok_response,
)
from robokassa.webhooks import (
    verify_result_signature as _verify_result_signature,
)
from robokassa.webhooks import (
    verify_success_signature as _verify_success_signature,
)

mcp: FastMCP = FastMCP("robokassa")


def _resolve_credential(explicit: str | None, env_var: str) -> str:
    value = explicit if explicit is not None else os.environ.get(env_var)
    if not value:
        raise ValueError(f"{env_var} is required — pass it explicitly or set the environment variable")
    return value


@mcp.tool()
async def check_payment(
    inv_id: int,
    merchant_login: str | None = None,
    password2: str | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Check the current state of a Robokassa payment by invoice ID.

    Uses the `OpStateExt` XML interface. Returns a structured summary including
    the state code (5/10/20/50/60/80/100), the OpKey (required later for
    initiating a refund via Refund/Create), sums, payment method, and any
    user-defined `Shp_*` parameters attached at checkout.

    State codes:
        5   — инициализирована, не оплачена
        10  — отменена (таймаут / пользователь)
        20  — HOLD (предавторизация)
        50  — средства получены, зачисление магазину
        60  — отказ в зачислении, средства возвращены покупателю
              (это НЕ пользовательский refund — для него используйте refund_status)
        80  — приостановлена (security check)
        100 — оплачена ✅

    Credentials may be passed explicitly or via ROBOKASSA_LOGIN / ROBOKASSA_PASSWORD2
    environment variables.

    Note:
        OpStateExt does NOT reflect post-payment refunds initiated through the
        Robokassa cabinet or Refund/Create. For that, store the requestId from
        Refund/Create and poll Refund/GetState.
    """
    login = _resolve_credential(merchant_login, "ROBOKASSA_LOGIN")
    pw2 = _resolve_credential(password2, "ROBOKASSA_PASSWORD2")

    state = await _check_payment(login, inv_id, pw2, algorithm=algorithm)

    return {
        "result_code": int(state.result_code),
        "state_code": int(state.state_code) if state.state_code is not None else None,
        "is_paid": state.is_paid,
        "is_terminal": state.is_terminal,
        "request_date": state.request_date.isoformat() if state.request_date else None,
        "state_date": state.state_date.isoformat() if state.state_date else None,
        "info": {
            "op_key": state.info.op_key,
            "inc_curr_label": state.info.inc_curr_label,
            "inc_sum": str(state.info.inc_sum) if state.info.inc_sum is not None else None,
            "inc_account": state.info.inc_account,
            "payment_method_code": state.info.payment_method_code,
            "out_curr_label": state.info.out_curr_label,
            "out_sum": str(state.info.out_sum) if state.info.out_sum is not None else None,
            "bank_card_rrn": state.info.bank_card_rrn,
        },
        "user_fields": state.user_fields,
    }


def _parse_refund_items(items: list[dict[str, Any]] | None) -> list[RefundInvoiceItem] | None:
    """Convert MCP-friendly dicts into `RefundInvoiceItem`s.

    Accepted keys per item: name, quantity, cost, tax, payment_method, payment_object.
    Enum fields accept their string values (e.g. `tax="vat20"`, `payment_object="service"`).
    """
    if items is None:
        return None
    if not items:
        return []
    from robokassa.refund import PaymentMethod, PaymentObject, TaxType

    parsed: list[RefundInvoiceItem] = []
    for raw in items:
        parsed.append(
            RefundInvoiceItem(
                name=str(raw["name"]),
                quantity=raw["quantity"] if isinstance(raw["quantity"], int) else Decimal(str(raw["quantity"])),
                cost=Decimal(str(raw["cost"])),
                tax=TaxType(raw.get("tax", TaxType.NONE.value)),
                payment_method=PaymentMethod(raw.get("payment_method", PaymentMethod.FULL_PAYMENT.value)),
                payment_object=PaymentObject(raw.get("payment_object", PaymentObject.COMMODITY.value)),
            )
        )
    return parsed


@mcp.tool()
async def refund_create(
    op_key: str,
    password3: str | None = None,
    refund_sum: float | None = None,
    items: list[dict[str, Any]] | None = None,
    algorithm: JwtAlgorithm = "HS256",
) -> dict[str, Any]:
    """Initiate a refund for a successful Robokassa payment.

    Requires `op_key` — obtained from `check_payment` (OpStateExt) or the
    `Result2` webhook payload for the original operation.

    Refund amount:
        - Omit `refund_sum` for a FULL refund of the original operation.
        - Pass a numeric amount for a partial refund.

    Fiscal receipt:
        - Omit `items` to refund without emitting a fiscal receipt (appropriate
          when the original sale was not fiscalized through Robokassa).
        - Pass a list of items to emit a receipt for the refund. Each item:
          `{name, quantity, cost, tax, payment_method, payment_object}` where
          tax ∈ none/vat0/vat5/vat7/vat10/vat20/vat105/vat107/vat110/vat120,
          payment_method ∈ full_payment/advance/..., payment_object ∈
          commodity/service/payment/...

    Authentication:
        Uses JWT signed with `Password#3`. This is distinct from Password#1
        (checkout) and Password#2 (XML status). Access to the Refund API must
        be enabled in the Robokassa cabinet separately.

    Returns:
        `{success: bool, request_id: str | None, message: str | None}`.
        Store `request_id` to poll refund status via `refund_status`.
        Common failure messages: NotEnoughOperationFunds, OperationNotFound,
        AlreadyRefunded.

    Credentials may be passed explicitly or via the ROBOKASSA_PASSWORD3 env var.
    """
    pw3 = _resolve_credential(password3, "ROBOKASSA_PASSWORD3")
    parsed_items = _parse_refund_items(items)
    amount = Decimal(str(refund_sum)) if refund_sum is not None else None

    result = await _refund_create(
        op_key,
        pw3,
        refund_sum=amount,
        items=parsed_items,
        algorithm=algorithm,
        raise_on_api_error=False,
    )
    return {
        "success": result.success,
        "request_id": result.request_id,
        "message": result.message,
    }


@mcp.tool()
async def refund_status(request_id: str) -> dict[str, Any]:
    """Check the current state of a previously-created refund request.

    Args:
        request_id: GUID returned by `refund_create()`.

    Returns:
        `{request_id, amount, state, is_finished, is_terminal}` where
        `state` ∈ `finished` / `processing` / `canceled`:
            - `finished` — возврат завершён (полный или частичный)
            - `processing` — возврат в процессе выполнения
            - `canceled` — возврат отменён через личный кабинет

    This endpoint requires no authentication beyond the request_id itself.
    If the request_id is invalid or not found, the call raises
    `RefundNotFoundError`.
    """
    result = await _refund_status(request_id)
    return {
        "request_id": result.request_id,
        "amount": str(result.amount),
        "state": result.state.value,
        "is_finished": result.is_finished,
        "is_terminal": result.is_terminal,
    }


def _build_checkout_receipt(
    items: list[dict[str, Any]] | None,
    sno: str | None,
) -> CheckoutReceipt | None:
    if items is None:
        return None
    parsed: list[CheckoutReceiptItem] = []
    for raw in items:
        parsed.append(
            CheckoutReceiptItem(
                name=str(raw["name"]),
                quantity=raw["quantity"] if isinstance(raw["quantity"], int) else Decimal(str(raw["quantity"])),
                sum=Decimal(str(raw["sum"])),
                tax=TaxType(raw.get("tax", TaxType.NONE.value)),
                payment_method=PaymentMethod(raw.get("payment_method", PaymentMethod.FULL_PAYMENT.value)),
                payment_object=PaymentObject(raw.get("payment_object", PaymentObject.COMMODITY.value)),
                nomenclature_code=raw.get("nomenclature_code"),
            )
        )
    return CheckoutReceipt(items=parsed, sno=sno)


@mcp.tool()
def create_invoice(
    out_sum: float,
    inv_id: int,
    description: str | None = None,
    merchant_login: str | None = None,
    password1: str | None = None,
    receipt_items: list[dict[str, Any]] | None = None,
    receipt_sno: str | None = None,
    shp_params: dict[str, Any] | None = None,
    email: str | None = None,
    culture: str = "ru",
    currency: str | None = None,
    is_test: bool = False,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Build a signed Robokassa checkout URL + form fields for a new payment.

    Does NOT make an HTTP request — produces the URL to redirect the user to.

    Args:
        out_sum: Amount to charge (any numeric type; normalized to 2 decimals).
        inv_id: Unique invoice number. Pass 0 to let Robokassa assign one.
        description: Human-readable order description.
        merchant_login: Shop ID. Falls back to ROBOKASSA_LOGIN env var.
        password1: Password#1. Falls back to ROBOKASSA_PASSWORD1 env var.
        receipt_items: Optional 54-ФЗ fiscal receipt items. Each item:
            `{name, quantity, sum, tax, payment_method, payment_object,
              nomenclature_code}`.
            Tax ∈ none / vat0 / vat5 / vat7 / vat10 / vat20 / vat105 / vat107 /
            vat110 / vat120.
        receipt_sno: Taxation scheme (`osn` / `usn_income` / etc.).
        shp_params: Extra `Shp_*` params echoed back in ResultURL. Keys may be
            passed without the `Shp_` prefix.
        email: Pre-fill customer email on the payment page.
        culture: UI locale (`ru` / `en` / `kk`).
        currency: Restrict to specific payment method (`IncCurrLabel`).
        is_test: Use sandbox checkout instead of production.
        algorithm: Signature hash algorithm.

    Returns:
        `{url, form_action, form_fields, signature, receipt_json}` —
        use `url` for a browser redirect, or `form_action` + `form_fields`
        for an HTML form post.
    """
    login = _resolve_credential(merchant_login, "ROBOKASSA_LOGIN")
    pw1 = _resolve_credential(password1, "ROBOKASSA_PASSWORD1")
    receipt = _build_checkout_receipt(receipt_items, receipt_sno)

    invoice = _create_invoice(
        merchant_login=login,
        out_sum=Decimal(str(out_sum)),
        inv_id=inv_id,
        password1=pw1,
        description=description,
        receipt=receipt,
        shp_params=shp_params,
        email=email,
        culture=culture,
        currency=currency,
        is_test=is_test,
        algorithm=algorithm,
    )
    return {
        "url": invoice.url,
        "form_action": invoice.form_action,
        "form_fields": invoice.form_fields,
        "signature": invoice.signature,
        "receipt_json": invoice.receipt_json,
    }


@mcp.tool()
def verify_result_signature(
    params: dict[str, Any],
    password2: str | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Verify the SignatureValue on a Robokassa ResultURL request.

    Robokassa POSTs payment notifications to the merchant's ResultURL after a
    successful checkout. The merchant must verify the signature to confirm the
    notification is authentic, then respond with the string returned by
    `build_ok_response(inv_id)` — otherwise Robokassa retries.

    Args:
        params: Form-encoded body from the ResultURL request. Must contain
            OutSum, InvId, SignatureValue. Any `Shp_*` parameters included in
            the body are automatically incorporated into signature verification.
        password2: Shop's Password#2. Falls back to ROBOKASSA_PASSWORD2 env var.
        algorithm: Signature algorithm configured in the cabinet.

    Returns:
        `{valid: bool, expected_ok_response: str}` — if `valid=True`, write
        `expected_ok_response` verbatim to the HTTP body.
    """
    pw2 = _resolve_credential(password2, "ROBOKASSA_PASSWORD2")
    valid = _verify_result_signature(params, pw2, algorithm=algorithm)
    inv_id = params.get("InvId") or params.get("invid") or params.get("invID") or ""
    return {
        "valid": valid,
        "expected_ok_response": _build_ok_response(inv_id) if valid else None,
    }


@mcp.tool()
def verify_success_signature(
    params: dict[str, Any],
    password1: str | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Verify the SignatureValue on a Robokassa SuccessURL redirect.

    SuccessURL is the browser-side redirect after payment completes. Unlike
    ResultURL it does NOT mean the payment is credited — only that the user
    returned to the success page. Still, verifying the signature guards against
    CSRF / tampering.

    Args:
        params: Query-string params from the SuccessURL GET request.
        password1: Shop's Password#1. Falls back to ROBOKASSA_PASSWORD1 env var.
        algorithm: Signature algorithm configured in the cabinet.

    Returns:
        `{valid: bool}`.
    """
    pw1 = _resolve_credential(password1, "ROBOKASSA_PASSWORD1")
    valid = _verify_success_signature(params, pw1, algorithm=algorithm)
    return {"valid": valid}


def main() -> None:
    """Entry point for the `robokassa-mcp` console script."""
    mcp.run()


if __name__ == "__main__":
    main()
