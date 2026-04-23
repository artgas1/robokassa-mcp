"""FastMCP server exposing Robokassa tools to AI agents."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from fastmcp import FastMCP

from robokassa import calc_out_sum as _calc_out_sum
from robokassa import check_payment as _check_payment
from robokassa import create_invoice as _create_invoice
from robokassa import list_currencies as _list_currencies
from robokassa import refund_create as _refund_create
from robokassa import refund_status as _refund_status
from robokassa.checkout import CheckoutReceipt, CheckoutReceiptItem
from robokassa.fiscal import second_receipt_create as _second_receipt_create
from robokassa.fiscal import second_receipt_status as _second_receipt_status
from robokassa.holding import hold_cancel as _hold_cancel
from robokassa.holding import hold_confirm as _hold_confirm
from robokassa.holding import hold_init as _hold_init
from robokassa.partner import partner_refund as _partner_refund
from robokassa.recurring import init_recurring_parent as _init_recurring_parent
from robokassa.recurring import recurring_charge as _recurring_charge
from robokassa.refund import JwtAlgorithm, PaymentMethod, PaymentObject, RefundInvoiceItem, TaxType
from robokassa.signatures import SignatureAlgorithm
from robokassa.sms import send_sms as _send_sms
from robokassa.split import SplitRecipient
from robokassa.split import build_split_invoice as _build_split_invoice
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


@mcp.tool()
async def list_currencies(
    merchant_login: str | None = None,
    language: str = "ru",
) -> dict[str, Any]:
    """List payment methods / currencies available to a Robokassa shop.

    Returns the full catalogue grouped by payment family (BankCard, SBP,
    SberPay, YandexPay, etc.) with per-method Label, Alias, Name, and
    min/max transaction bounds where applicable.

    The Label values are what you pass as `IncCurrLabel` when calling
    `create_invoice` to restrict the user to a specific payment method.

    No password / signature required — GetCurrencies is a public endpoint.

    Args:
        merchant_login: Shop identifier. Falls back to ROBOKASSA_LOGIN env var.
        language: UI language for Name fields (`ru` / `en`).
    """
    login = _resolve_credential(merchant_login, "ROBOKASSA_LOGIN")
    listing = await _list_currencies(login, language=language)
    return {
        "result_code": int(listing.result_code),
        "groups": [
            {
                "code": g.code,
                "description": g.description,
                "currencies": [
                    {
                        "label": c.label,
                        "alias": c.alias,
                        "name": c.name,
                        "min_value": str(c.min_value) if c.min_value is not None else None,
                        "max_value": str(c.max_value) if c.max_value is not None else None,
                    }
                    for c in g.currencies
                ],
            }
            for g in listing.groups
        ],
    }


@mcp.tool()
async def calc_out_sum(
    inc_sum: float,
    merchant_login: str | None = None,
    password1: str | None = None,
    inc_curr_label: str | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Calculate the amount credited to the shop for a given customer payment.

    Useful for showing the commission / final sum in checkout UI.

    Signature: `<algorithm>(MerchantLogin:IncSum:Password#1)`.

    Args:
        inc_sum: Amount the customer pays.
        merchant_login: Falls back to ROBOKASSA_LOGIN.
        password1: Falls back to ROBOKASSA_PASSWORD1.
        inc_curr_label: Specific payment method label from `list_currencies`.
            If omitted, Robokassa calculates for the default method.
        algorithm: Signature algorithm configured in the cabinet.

    Returns:
        `{out_sum: str | None, result_code: int}`.
    """
    login = _resolve_credential(merchant_login, "ROBOKASSA_LOGIN")
    pw1 = _resolve_credential(password1, "ROBOKASSA_PASSWORD1")
    result = await _calc_out_sum(
        login,
        Decimal(str(inc_sum)),
        pw1,
        inc_curr_label=inc_curr_label,
        algorithm=algorithm,
    )
    return {
        "result_code": int(result.result_code),
        "out_sum": str(result.out_sum) if result.out_sum is not None else None,
    }


@mcp.tool()
def hold_init(
    out_sum: float,
    inv_id: int,
    description: str | None = None,
    merchant_login: str | None = None,
    password1: str | None = None,
    receipt_items: list[dict[str, Any]] | None = None,
    receipt_sno: str | None = None,
    email: str | None = None,
    culture: str = "ru",
    is_test: bool = False,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Build a checkout URL with StepByStep=true for two-step pre-auth.

    Funds are reserved on the card; use `hold_confirm` to capture or
    `hold_cancel` to release. Max hold window: 7 days.

    Notification for successful hold is delivered to ResultURL2 (not the
    standard ResultURL). Requires prior agreement with Robokassa and only
    works with card payments.
    """
    login = _resolve_credential(merchant_login, "ROBOKASSA_LOGIN")
    pw1 = _resolve_credential(password1, "ROBOKASSA_PASSWORD1")
    receipt = _build_checkout_receipt(receipt_items, receipt_sno)
    invoice = _hold_init(
        merchant_login=login,
        out_sum=Decimal(str(out_sum)),
        inv_id=inv_id,
        password1=pw1,
        description=description,
        receipt=receipt,
        email=email,
        culture=culture,
        is_test=is_test,
        algorithm=algorithm,
    )
    return {
        "url": invoice.url,
        "form_action": invoice.form_action,
        "form_fields": invoice.form_fields,
        "signature": invoice.signature,
    }


@mcp.tool()
async def hold_confirm(
    out_sum: float,
    inv_id: int,
    merchant_login: str | None = None,
    password1: str | None = None,
    receipt_items: list[dict[str, Any]] | None = None,
    receipt_sno: str | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Capture previously-reserved funds for a held transaction.

    Cart can be reduced (smaller `receipt_items`) before capture, but not
    increased. Pass the same OutSum (possibly smaller) as the original hold.
    """
    login = _resolve_credential(merchant_login, "ROBOKASSA_LOGIN")
    pw1 = _resolve_credential(password1, "ROBOKASSA_PASSWORD1")
    receipt = _build_checkout_receipt(receipt_items, receipt_sno)
    result = await _hold_confirm(
        merchant_login=login,
        out_sum=Decimal(str(out_sum)),
        inv_id=inv_id,
        password1=pw1,
        receipt=receipt,
        algorithm=algorithm,
    )
    return {"status_code": result.status_code, "body": result.body}


@mcp.tool()
async def hold_cancel(
    inv_id: int,
    merchant_login: str | None = None,
    password1: str | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Release a hold without capturing the reserved funds."""
    login = _resolve_credential(merchant_login, "ROBOKASSA_LOGIN")
    pw1 = _resolve_credential(password1, "ROBOKASSA_PASSWORD1")
    result = await _hold_cancel(
        merchant_login=login,
        inv_id=inv_id,
        password1=pw1,
        algorithm=algorithm,
    )
    return {"status_code": result.status_code, "body": result.body}


@mcp.tool()
def init_recurring_parent(
    out_sum: float,
    inv_id: int,
    description: str | None = None,
    merchant_login: str | None = None,
    password1: str | None = None,
    receipt_items: list[dict[str, Any]] | None = None,
    receipt_sno: str | None = None,
    email: str | None = None,
    culture: str = "ru",
    is_test: bool = False,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Build a checkout URL marking the payment as a recurring parent.

    After the user pays, the shop can silently charge subsequent amounts
    via `recurring_charge` citing this invoice's `inv_id`.
    """
    login = _resolve_credential(merchant_login, "ROBOKASSA_LOGIN")
    pw1 = _resolve_credential(password1, "ROBOKASSA_PASSWORD1")
    receipt = _build_checkout_receipt(receipt_items, receipt_sno)
    invoice = _init_recurring_parent(
        merchant_login=login,
        out_sum=Decimal(str(out_sum)),
        inv_id=inv_id,
        password1=pw1,
        description=description,
        receipt=receipt,
        email=email,
        culture=culture,
        is_test=is_test,
        algorithm=algorithm,
    )
    return {
        "url": invoice.url,
        "form_action": invoice.form_action,
        "form_fields": invoice.form_fields,
        "signature": invoice.signature,
    }


@mcp.tool()
async def recurring_charge(
    new_inv_id: int,
    previous_inv_id: int,
    out_sum: float,
    description: str | None = None,
    merchant_login: str | None = None,
    password1: str | None = None,
    receipt_items: list[dict[str, Any]] | None = None,
    receipt_sno: str | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Silently charge a recurring subscription payment.

    `previous_inv_id` must be the inv_id of an already-paid parent (created
    with `init_recurring_parent`). Response `"OK<InvId>"` means accepted,
    NOT captured — verify via `check_payment`.
    """
    login = _resolve_credential(merchant_login, "ROBOKASSA_LOGIN")
    pw1 = _resolve_credential(password1, "ROBOKASSA_PASSWORD1")
    receipt = _build_checkout_receipt(receipt_items, receipt_sno)
    result = await _recurring_charge(
        merchant_login=login,
        new_inv_id=new_inv_id,
        previous_inv_id=previous_inv_id,
        out_sum=Decimal(str(out_sum)),
        password1=pw1,
        description=description,
        receipt=receipt,
        algorithm=algorithm,
    )
    return {
        "status_code": result.status_code,
        "body": result.body,
        "is_accepted": result.is_accepted,
    }


@mcp.tool()
def build_split_invoice(
    out_amount: float,
    splits: list[dict[str, Any]],
    email: str | None = None,
    inc_curr: str | None = None,
    inv_id: int | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Build a URL for a multi-recipient (marketplace-style) split payment.

    Each split: `{merchantLogin, amount, description?}`. Sum of amounts
    must equal out_amount.
    """
    parsed = [
        SplitRecipient(
            merchant_login=str(s["merchantLogin"]),
            amount=Decimal(str(s["amount"])),
            description=s.get("description"),
        )
        for s in splits
    ]
    invoice = _build_split_invoice(
        out_amount=Decimal(str(out_amount)),
        splits=parsed,
        email=email,
        inc_curr=inc_curr,
        inv_id=inv_id,
        description=description,
    )
    return {"url": invoice.url, "invoice_json": invoice.invoice_json}


@mcp.tool()
async def send_sms(
    phone: str,
    message: str,
    merchant_login: str | None = None,
    password1: str | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> dict[str, Any]:
    """Send an SMS via Robokassa's SMS service.

    Paid feature — requires a non-zero SMS balance in the cabinet.
    Phone must be in international format (e.g. `79991234567`).
    """
    login = _resolve_credential(merchant_login, "ROBOKASSA_LOGIN")
    pw1 = _resolve_credential(password1, "ROBOKASSA_PASSWORD1")
    result = await _send_sms(login, phone, message, pw1, algorithm=algorithm)
    return {"status_code": result.status_code, "body": result.body}


@mcp.tool()
async def second_receipt_create(
    merchant_id: str,
    receipt_id: str,
    origin_id: str,
    items: list[dict[str, Any]],
    total: float,
    payments: list[dict[str, Any]],
    client: dict[str, str],
    url: str,
    password1: str | None = None,
    sno: str | None = None,
    vats: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Emit a final (second) 54-ФЗ fiscal receipt after an advance/prepayment sale.

    For merchants using Robokassa Fiscal. `merchant_id` is the Fiscal
    merchantId (e.g. `robokassa_sell`); `origin_id` is the InvId of the
    original operation. Max 2 receipts per operation.

    items: `[{name, quantity, sum, tax, payment_method, payment_object}]`.
    payments: typically `[{type: 2, sum: <total>}]` for offsetting a prepayment.
    client: `{email}` or `{phone}`.
    """
    pw1 = _resolve_credential(password1, "ROBOKASSA_PASSWORD1")
    result = await _second_receipt_create(
        merchant_id=merchant_id,
        receipt_id=receipt_id,
        origin_id=origin_id,
        items=items,
        total=total,
        client=client,
        payments=payments,
        password1=pw1,
        sno=sno,
        url=url,
        vats=vats,
    )
    return {
        "result_code": result.result_code,
        "result_description": result.result_description,
    }


@mcp.tool()
async def second_receipt_status(
    merchant_id: str,
    receipt_id: str,
    password1: str | None = None,
) -> dict[str, Any]:
    """Check registration status of a 54-ФЗ fiscal receipt.

    Use `merchant_id="robokassa_state"` for status lookups.
    """
    pw1 = _resolve_credential(password1, "ROBOKASSA_PASSWORD1")
    result = await _second_receipt_status(
        merchant_id=merchant_id,
        receipt_id=receipt_id,
        password1=pw1,
    )
    return {
        "code": result.code,
        "description": result.description,
        "fn_number": result.fn_number,
        "fiscal_document_number": result.fiscal_document_number,
        "fiscal_document_attribute": result.fiscal_document_attribute,
        "fiscal_date": result.fiscal_date,
        "fiscal_type": result.fiscal_type,
    }


@mcp.tool()
async def partner_refund(
    robox_partner_id: str,
    op_key: str,
    auth_headers: dict[str, str],
    refund_sum: float | None = None,
    receipt: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Alternative refund path via Partner API (for CPA / SaaS integrators).

    Merchant-only users should prefer `refund_create` instead (uses Password#3).
    Partner API requires `RoboxPartnerId` and partner-specific auth headers —
    typically `{"Authorization": "Bearer <partner-jwt>"}`.
    """
    amount = Decimal(str(refund_sum)) if refund_sum is not None else None
    result = await _partner_refund(
        robox_partner_id=robox_partner_id,
        op_key=op_key,
        auth_headers=auth_headers,
        refund_sum=amount,
        receipt=receipt,
        raise_on_api_error=False,
    )
    return {
        "success": result.success,
        "error": result.error,
        "result_code": result.result_code,
    }


def main() -> None:
    """Entry point for the `robokassa-mcp` console script.

    Defaults to stdio transport (Claude Desktop / Claude Code / Cursor standard).
    Pass `--transport http` (or `sse`) to run as an HTTP server — useful for
    remote MCP setups and for `npx @modelcontextprotocol/inspector`.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="robokassa-mcp",
        description="MCP server for the Robokassa payment gateway.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "streamable-http", "sse"],
        default="stdio",
        help="MCP transport to use (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind when transport is http/sse (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind when transport is http/sse (default: 8000).",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
