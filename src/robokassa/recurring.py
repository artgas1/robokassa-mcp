"""Robokassa recurring payments (subscription auto-charges).

Flow:
    1. Parent payment: ordinary checkout with `Recurring=true`. After user
       pays, Robokassa stores a token enabling future silent charges.
    2. Child payment: POST to `/Merchant/Recurring` citing the parent's
       `InvoiceId` via `PreviousInvoiceID`. No user interaction needed.

Caveat: the POST response `OK<InvId>` means the operation was accepted,
NOT that the charge succeeded. Always verify with ResultURL or OpStateExt.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import httpx

from robokassa.checkout import CheckoutInvoice, CheckoutReceipt, create_invoice
from robokassa.signatures import SignatureAlgorithm, compute_signature

RECURRING_URL: Final[str] = "https://auth.robokassa.ru/Merchant/Recurring"


@dataclass(frozen=True, slots=True)
class RecurringChargeResult:
    """Raw response from POST /Merchant/Recurring."""

    status_code: int
    body: str

    @property
    def is_accepted(self) -> bool:
        """Robokassa returns 'OK<InvId>' on successful submission (not capture)."""
        return self.status_code == 200 and self.body.strip().lower().startswith("ok")


def init_recurring_parent(
    *,
    merchant_login: str,
    out_sum: Decimal | float | int | str,
    inv_id: int | str,
    password1: str,
    description: str | None = None,
    receipt: CheckoutReceipt | None = None,
    shp_params: dict[str, Any] | None = None,
    email: str | None = None,
    culture: str = "ru",
    is_test: bool = False,
    algorithm: SignatureAlgorithm = "md5",
) -> CheckoutInvoice:
    """Build a checkout URL that enables recurring charges after payment.

    This is `create_invoice` + `Recurring=true`. The parameter does NOT
    participate in signature — it just marks the payment as a subscription
    parent.
    """
    invoice = create_invoice(
        merchant_login=merchant_login,
        out_sum=out_sum,
        inv_id=inv_id,
        password1=password1,
        description=description,
        receipt=receipt,
        shp_params=shp_params,
        email=email,
        culture=culture,
        is_test=is_test,
        algorithm=algorithm,
    )
    fields = dict(invoice.form_fields)
    fields["Recurring"] = "true"
    from urllib.parse import urlencode

    url = f"{invoice.form_action}?{urlencode(fields, safe='')}"
    return CheckoutInvoice(
        url=url,
        form_action=invoice.form_action,
        form_fields=fields,
        signature=invoice.signature,
        receipt_json=invoice.receipt_json,
    )


def _format_out_sum(out_sum: Decimal | float | int | str) -> str:
    if isinstance(out_sum, Decimal):
        return f"{out_sum:.2f}"
    if isinstance(out_sum, int | float):
        return f"{Decimal(str(out_sum)):.2f}"
    return str(out_sum)


async def recurring_charge(
    *,
    merchant_login: str,
    new_inv_id: int | str,
    previous_inv_id: int | str,
    out_sum: Decimal | float | int | str,
    password1: str,
    description: str | None = None,
    receipt: CheckoutReceipt | None = None,
    recurring_url: str = RECURRING_URL,
    algorithm: SignatureAlgorithm = "md5",
    http_client: httpx.AsyncClient | None = None,
) -> RecurringChargeResult:
    """POST a child recurring charge to Robokassa.

    Signature: `<algorithm>(MerchantLogin:OutSum:NewInvoiceId:[Receipt:]Password#1)`.
    PreviousInvoiceID is sent in the POST body but NOT included in signature.

    Response body `"OK<InvId>"` means the operation was accepted. To verify
    actual capture, poll via `check_payment(new_inv_id)` (OpStateExt) or
    rely on the standard ResultURL webhook.
    """
    out_sum_str = _format_out_sum(out_sum)
    receipt_json = receipt.to_json() if receipt is not None else None

    parts: list[str] = [merchant_login, out_sum_str, str(new_inv_id)]
    if receipt_json is not None:
        parts.append(receipt_json)
    parts.append(password1)
    signature = compute_signature(*parts, algorithm=algorithm)

    form: dict[str, str] = {
        "MerchantLogin": merchant_login,
        "InvoiceID": str(new_inv_id),
        "PreviousInvoiceID": str(previous_inv_id),
        "OutSum": out_sum_str,
        "SignatureValue": signature,
    }
    if description is not None:
        form["Description"] = description
    if receipt_json is not None:
        from urllib.parse import quote

        form["Receipt"] = quote(receipt_json, safe="")

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(recurring_url, data=form)
        response.raise_for_status()
        return RecurringChargeResult(status_code=response.status_code, body=response.text)
    finally:
        if owns_client:
            await client.aclose()


__all__ = [
    "RECURRING_URL",
    "RecurringChargeResult",
    "init_recurring_parent",
    "recurring_charge",
]
