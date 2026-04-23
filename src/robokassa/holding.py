"""Robokassa card holding / pre-authorization (StepByStep).

Flow:
    1. hold_init() — send user to checkout with ``StepByStep=true``. Funds are
       reserved on the card for up to 7 days. Notification arrives on
       **ResultURL2** (not the standard ResultURL).
    2. hold_confirm() — POST to capture the reserved funds. Can reduce the
       cart (pass a smaller `receipt`). Standard ResultURL fires after.
    3. hold_cancel() — POST to release the hold without capturing.

This feature requires prior agreement with Robokassa and only works with
card payments.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import httpx

from robokassa.checkout import CheckoutInvoice, CheckoutReceipt, create_invoice
from robokassa.signatures import SignatureAlgorithm, compute_signature

HOLD_CONFIRM_URL: Final[str] = "https://auth.robokassa.ru/Merchant/Payment/Confirm"
HOLD_CANCEL_URL: Final[str] = "https://auth.robokassa.ru/Merchant/Payment/Cancel"


@dataclass(frozen=True, slots=True)
class HoldingActionResult:
    """Result of a hold_confirm / hold_cancel HTTP POST."""

    status_code: int
    body: str


def hold_init(
    *,
    merchant_login: str,
    out_sum: Decimal | float | int | str,
    inv_id: int | str,
    password1: str,
    description: str | None = None,
    receipt: CheckoutReceipt | None = None,
    shp_params: Mapping[str, Any] | None = None,
    email: str | None = None,
    culture: str = "ru",
    is_test: bool = False,
    algorithm: SignatureAlgorithm = "md5",
) -> CheckoutInvoice:
    """Build a signed checkout URL with StepByStep=true for a 2-step payment.

    Signature order for hold init:
        MerchantLogin : OutSum : InvoiceId : [Receipt :] true : Password#1

    `StepByStep=true` participates in the signature between Password#1 and
    the usual position — we thread it into `shp_params` so `create_invoice`
    handles ordering correctly. But Robokassa docs put `true` right before
    Password#1, not after — so we handle that manually.

    Note: hold success is delivered to **ResultURL2**, not ResultURL.
    """
    # Robokassa's exact signature for hold-init is:
    #     MerchantLogin:OutSum:InvoiceId:Receipt:true:Password1
    # We can't reuse create_invoice's signature builder because `true` sits
    # between Receipt and Password1. Build manually and pass as override.
    from robokassa.signatures import compute_signature as _compute

    out_sum_str = _format_out_sum(out_sum)
    receipt_json = receipt.to_json() if receipt is not None else None

    parts: list[str] = [merchant_login, out_sum_str, str(inv_id)]
    if receipt_json is not None:
        parts.append(receipt_json)
    parts.append("true")
    parts.append(password1)
    # Shp_ params appended alphabetically at the end (same rule as checkout).
    if shp_params:
        shp_sorted = sorted(
            ((str(k), str(v)) for k, v in shp_params.items()),
            key=lambda kv: kv[0].lower(),
        )
        parts.extend(f"{k if k.lower().startswith('shp_') else f'Shp_{k}'}={v}" for k, v in shp_sorted)
    signature = _compute(*parts, algorithm=algorithm)

    # Build a "regular" invoice then mutate the StepByStep flag + signature.
    invoice = create_invoice(
        merchant_login=merchant_login,
        out_sum=out_sum_str,
        inv_id=inv_id,
        password1=password1,  # not used since we override signature below
        description=description,
        receipt=receipt,
        shp_params=shp_params,
        email=email,
        culture=culture,
        is_test=is_test,
        algorithm=algorithm,
    )
    fields = dict(invoice.form_fields)
    fields["StepByStep"] = "true"
    fields["SignatureValue"] = signature
    from urllib.parse import urlencode

    url = f"{invoice.form_action}?{urlencode(fields, safe='')}"

    return CheckoutInvoice(
        url=url,
        form_action=invoice.form_action,
        form_fields=fields,
        signature=signature,
        receipt_json=receipt_json,
    )


def _format_out_sum(out_sum: Decimal | float | int | str) -> str:
    if isinstance(out_sum, Decimal):
        return f"{out_sum:.2f}"
    if isinstance(out_sum, int | float):
        return f"{Decimal(str(out_sum)):.2f}"
    return str(out_sum)


async def hold_confirm(
    *,
    merchant_login: str,
    out_sum: Decimal | float | int | str,
    inv_id: int | str,
    password1: str,
    receipt: CheckoutReceipt | None = None,
    confirm_url: str = HOLD_CONFIRM_URL,
    algorithm: SignatureAlgorithm = "md5",
    http_client: httpx.AsyncClient | None = None,
) -> HoldingActionResult:
    """Capture previously-reserved funds via POST /Merchant/Payment/Confirm.

    Signature without receipt (unchanged cart):
        MerchantLogin : OutSum : InvoiceId : Password#1

    Signature with receipt (cart reduced before capture):
        MerchantLogin : OutSum : InvoiceId : Receipt : Password#1

    Cart can only be reduced, never increased, before capture.
    """
    out_sum_str = _format_out_sum(out_sum)
    receipt_json = receipt.to_json() if receipt is not None else None

    parts: list[str] = [merchant_login, out_sum_str, str(inv_id)]
    if receipt_json is not None:
        parts.append(receipt_json)
    parts.append(password1)
    signature = compute_signature(*parts, algorithm=algorithm)

    form: dict[str, str] = {
        "MerchantLogin": merchant_login,
        "InvoiceID": str(inv_id),
        "OutSum": out_sum_str,
        "SignatureValue": signature,
    }
    if receipt_json is not None:
        from urllib.parse import quote

        form["Receipt"] = quote(receipt_json, safe="")

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(confirm_url, data=form)
        response.raise_for_status()
        return HoldingActionResult(status_code=response.status_code, body=response.text)
    finally:
        if owns_client:
            await client.aclose()


async def hold_cancel(
    *,
    merchant_login: str,
    inv_id: int | str,
    password1: str,
    cancel_url: str = HOLD_CANCEL_URL,
    algorithm: SignatureAlgorithm = "md5",
    http_client: httpx.AsyncClient | None = None,
) -> HoldingActionResult:
    """Release a hold without capturing via POST /Merchant/Payment/Cancel.

    Signature uses an empty OutSum slot:
        MerchantLogin :: InvoiceId : Password#1

    (That's literally a double colon — OutSum is absent from the signature
    string even though it may be present in the POST body.)
    """
    signature = compute_signature(merchant_login, "", str(inv_id), password1, algorithm=algorithm)
    form: dict[str, str] = {
        "MerchantLogin": merchant_login,
        "InvoiceID": str(inv_id),
        "SignatureValue": signature,
    }
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(cancel_url, data=form)
        response.raise_for_status()
        return HoldingActionResult(status_code=response.status_code, body=response.text)
    finally:
        if owns_client:
            await client.aclose()


__all__ = [
    "HOLD_CANCEL_URL",
    "HOLD_CONFIRM_URL",
    "HoldingActionResult",
    "hold_cancel",
    "hold_confirm",
    "hold_init",
]
