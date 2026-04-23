"""Split payments — marketplace-style multi-recipient checkout.

Endpoint: `POST https://auth.robokassa.ru/Merchant/Payment/CreateV2`

The request carries a JSON blob (URL-encoded in the `invoice` query param)
describing the total `outAmount` plus per-recipient shares under `splits`.

This module builds the URL; callers are responsible for redirecting the
user or POSTing the form. See
https://docs.robokassa.ru/ru/split-payments for the latest signature
requirements, which depend on the merchant-level settings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final
from urllib.parse import urlencode

DEFAULT_SPLIT_URL: Final[str] = "https://auth.robokassa.ru/Merchant/Payment/CreateV2"


@dataclass(frozen=True, slots=True)
class SplitRecipient:
    """One leg of a split payment — merchantLogin + amount."""

    merchant_login: str
    amount: Decimal | float
    description: str | None = None


@dataclass(frozen=True, slots=True)
class SplitInvoice:
    """Result of building a split-payment URL."""

    url: str
    invoice_json: str
    splits: list[SplitRecipient] = field(default_factory=lambda: [])


def build_split_invoice(
    *,
    out_amount: Decimal | float,
    splits: list[SplitRecipient],
    email: str | None = None,
    inc_curr: str | None = None,
    inv_id: int | str | None = None,
    description: str | None = None,
    extra: dict[str, Any] | None = None,
    url: str = DEFAULT_SPLIT_URL,
) -> SplitInvoice:
    """Build the URL for a multi-recipient (split) payment.

    Args:
        out_amount: Total amount the customer will pay.
        splits: List of recipient/amount pairs. Sum of amounts should equal
            out_amount.
        email: Customer email (optional).
        inc_curr: Restrict payment method (`IncCurrLabel`).
        inv_id: Invoice id (optional — if omitted, Robokassa assigns).
        description: Human-readable order description.
        extra: Any additional keys to include in the JSON payload.

    Returns:
        `SplitInvoice` with the redirect URL and the raw JSON payload.

    Note:
        Signature requirements for split payments depend on the cabinet
        configuration. See https://docs.robokassa.ru/ru/split-payments.
        This helper focuses on URL construction; callers may need to add
        signature fields depending on their setup.
    """
    if not splits:
        raise ValueError("splits must contain at least one recipient")

    total = sum(Decimal(str(s.amount)) for s in splits)
    expected = Decimal(str(out_amount))
    if total != expected:
        raise ValueError(f"splits sum to {total}, expected {expected}")

    payload: dict[str, Any] = {
        "outAmount": float(out_amount),
        "splits": [
            {
                "merchantLogin": s.merchant_login,
                "amount": float(s.amount),
                **({"description": s.description} if s.description else {}),
            }
            for s in splits
        ],
    }
    if email is not None:
        payload["email"] = email
    if inc_curr is not None:
        payload["incCurr"] = inc_curr
    if inv_id is not None:
        payload["invoiceId"] = str(inv_id)
    if description is not None:
        payload["description"] = description
    if extra:
        payload.update(extra)

    invoice_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    full_url = f"{url}?{urlencode({'invoice': invoice_json})}"
    return SplitInvoice(url=full_url, invoice_json=invoice_json, splits=list(splits))


__all__ = [
    "DEFAULT_SPLIT_URL",
    "SplitInvoice",
    "SplitRecipient",
    "build_split_invoice",
]
