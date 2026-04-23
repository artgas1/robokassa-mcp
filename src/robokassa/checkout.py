"""Robokassa checkout (payinit) helpers — build signed payment URLs.

The checkout endpoint is `https://auth.robokassa.ru/Merchant/Index.aspx`. We
do not POST directly; instead we construct a signed URL (for redirects) and
the corresponding form fields (for HTML form embeds).

Signature formula:

    <algorithm>(MerchantLogin:OutSum:InvId:[Receipt:]Password#1[:Shp_key=value ...])

Receipt (if present) participates in the signature as a compact JSON string
between `InvId` and `Password#1`. Shp_ custom params are appended
alphabetically (case-insensitive) at the end.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final
from urllib.parse import quote, urlencode

from robokassa.refund import PaymentMethod, PaymentObject, TaxType
from robokassa.signatures import SignatureAlgorithm, compute_signature

DEFAULT_CHECKOUT_URL: Final[str] = "https://auth.robokassa.ru/Merchant/Index.aspx"


@dataclass(frozen=True, slots=True)
class CheckoutReceiptItem:
    """One line item in a 54-ФЗ fiscal receipt attached to a checkout.

    Note on field naming: the checkout Receipt uses `sum` + `tax` (snake_case),
    which differs from the RefundInvoiceItem shape (`Cost` + `Tax`). Both are
    mandated by Robokassa's two different endpoints.
    """

    name: str
    quantity: int | Decimal
    sum: Decimal
    tax: TaxType = TaxType.NONE
    payment_method: PaymentMethod = PaymentMethod.FULL_PAYMENT
    payment_object: PaymentObject = PaymentObject.COMMODITY
    nomenclature_code: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "quantity": self.quantity if isinstance(self.quantity, int) else float(self.quantity),
            "sum": float(self.sum),
            "payment_method": self.payment_method.value,
            "payment_object": self.payment_object.value,
            "tax": self.tax.value,
        }
        if self.nomenclature_code is not None:
            payload["nomenclature_code"] = self.nomenclature_code
        return payload


@dataclass(frozen=True, slots=True)
class CheckoutReceipt:
    """A Robokassa 54-ФЗ receipt is a wrapper around `items` plus optional SNO."""

    items: list[CheckoutReceiptItem]
    sno: str | None = None  # taxation scheme (e.g. 'osn', 'usn_income', ...)

    def to_json(self) -> str:
        """Serialize to the compact JSON string used in signature and URL."""
        body: dict[str, Any] = {"items": [item.to_payload() for item in self.items]}
        if self.sno is not None:
            body["sno"] = self.sno
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class CheckoutInvoice:
    """Signed checkout payload ready for redirect or HTML form embedding."""

    url: str
    """Full signed URL for a browser redirect."""

    form_action: str
    """URL to POST a form to (same as the URL's path + query)."""

    form_fields: dict[str, str] = field(default_factory=lambda: {})
    """All key/value pairs to emit as hidden form inputs."""

    signature: str = ""
    """The computed SignatureValue (also present inside form_fields and url)."""

    receipt_json: str | None = None
    """Raw JSON string that was fed into the signature (if any receipt)."""


def _format_out_sum(out_sum: Decimal | float | int | str) -> str:
    """Robokassa requires amounts with exactly two decimal places."""
    if isinstance(out_sum, Decimal):
        return f"{out_sum:.2f}"
    if isinstance(out_sum, int | float):
        return f"{Decimal(str(out_sum)):.2f}"
    return str(out_sum)


def build_checkout_signature(
    *,
    merchant_login: str,
    out_sum: str,
    inv_id: int | str,
    password1: str,
    receipt_json: str | None = None,
    shp_params: Mapping[str, Any] | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> str:
    """Build the SignatureValue for the checkout URL.

    Order of parts (in Robokassa's docs):
        MerchantLogin : OutSum : InvId : [Receipt :] Password#1 [: Shp_* ...]
    """
    parts: list[str] = [merchant_login, out_sum, str(inv_id)]
    if receipt_json is not None:
        parts.append(receipt_json)
    parts.append(password1)
    if shp_params:
        shp_items = sorted(
            ((str(k), str(v)) for k, v in shp_params.items()),
            key=lambda kv: kv[0].lower(),
        )
        parts.extend(f"{k}={v}" for k, v in shp_items)
    return compute_signature(*parts, algorithm=algorithm)


def create_invoice(
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
    currency: str | None = None,
    expiration_date: str | None = None,
    is_test: bool = False,
    checkout_url: str = DEFAULT_CHECKOUT_URL,
    algorithm: SignatureAlgorithm = "md5",
) -> CheckoutInvoice:
    """Build a signed checkout URL + form fields for Robokassa payinit.

    Args:
        merchant_login: Shop identifier.
        out_sum: Amount. Any numeric type — normalized to 2 decimal places.
        inv_id: Invoice number. Use 0 to let Robokassa assign one.
        password1: Shop's Password#1.
        description: Human-readable order description (shown on payment page).
        receipt: Optional 54-ФЗ fiscal receipt.
        shp_params: Custom `Shp_*` params echoed back in ResultURL. Keys can
            be passed without the `Shp_` prefix — we add it if missing.
        email: Pre-fill customer email on the payment page.
        culture: UI locale — `ru` / `en` / `kk` (Robokassa supports a few).
        currency: `IncCurrLabel` value from `list_currencies` (optional).
        expiration_date: `ExpirationDate` ISO 8601 (optional, max 30 days).
        is_test: Open the sandbox payment form instead of production.
        checkout_url: Override for the base URL (for testing).
        algorithm: Signature algorithm configured in the cabinet.

    Returns:
        `CheckoutInvoice` with `url` (redirect), `form_fields` (HTML form),
        and the raw signature + receipt_json for debugging.
    """
    out_sum_str = _format_out_sum(out_sum)

    # Normalize Shp_ params — accept both `order_id` and `Shp_order_id` keys.
    normalized_shp: dict[str, str] = {}
    if shp_params:
        for key, value in shp_params.items():
            prefixed = key if key.lower().startswith("shp_") else f"Shp_{key}"
            normalized_shp[prefixed] = str(value)

    receipt_json = receipt.to_json() if receipt is not None else None

    signature = build_checkout_signature(
        merchant_login=merchant_login,
        out_sum=out_sum_str,
        inv_id=inv_id,
        password1=password1,
        receipt_json=receipt_json,
        shp_params=normalized_shp or None,
        algorithm=algorithm,
    )

    fields: dict[str, str] = {
        "MerchantLogin": merchant_login,
        "OutSum": out_sum_str,
        "InvId": str(inv_id),
        "SignatureValue": signature,
        "Culture": culture,
    }
    if description is not None:
        fields["Description"] = description
    if email is not None:
        fields["Email"] = email
    if currency is not None:
        fields["IncCurrLabel"] = currency
    if expiration_date is not None:
        fields["ExpirationDate"] = expiration_date
    if is_test:
        fields["IsTest"] = "1"
    if receipt_json is not None:
        # Single URL-encode — consumers that build a URL from `form_fields` via
        # urlencode() will do the second pass implicitly.
        fields["Receipt"] = quote(receipt_json, safe="")
    fields.update(normalized_shp)

    url = f"{checkout_url}?{urlencode(fields, safe='')}"

    return CheckoutInvoice(
        url=url,
        form_action=checkout_url,
        form_fields=fields,
        signature=signature,
        receipt_json=receipt_json,
    )


__all__ = [
    "DEFAULT_CHECKOUT_URL",
    "CheckoutInvoice",
    "CheckoutReceipt",
    "CheckoutReceiptItem",
    "build_checkout_signature",
    "create_invoice",
]
