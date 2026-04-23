"""Robokassa Refund API — initiate and track refunds.

Base URL: `https://services.robokassa.ru/RefundService/`.

Authentication uses a JWT signed with the merchant's `Password#3`. Access to
the Refund API must first be enabled in the Robokassa cabinet and `Password#3`
generated separately from Password#1 / Password#2.

Note on JSON compactness: Robokassa requires the JWT payload to be a compact
JSON object (no extra whitespace). PyJWT encodes with
`json.dumps(separators=(",", ":"))` by default, which satisfies this.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, Literal

import httpx
import jwt

from robokassa.types import RobokassaApiError, RobokassaResponseError

DEFAULT_REFUND_BASE_URL: Final[str] = "https://services.robokassa.ru/RefundService"

JwtAlgorithm = Literal["HS256", "HS384", "HS512"]


class RefundState(StrEnum):
    """Status of a refund request returned by Refund/GetState."""

    FINISHED = "finished"
    """Возврат завершён (полный или частичный)."""

    PROCESSING = "processing"
    """Возврат в процессе выполнения."""

    CANCELED = "canceled"
    """Возврат отменён через личный кабинет."""


class PaymentMethod(StrEnum):
    """Fiscal payment method (54-ФЗ). Values from Robokassa receipt spec."""

    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    ADVANCE = "advance"
    FULL_PREPAYMENT = "full_prepayment"
    PARTIAL_PREPAYMENT = "partial_prepayment"
    CREDIT = "credit"
    CREDIT_PAYMENT = "credit_payment"


class PaymentObject(StrEnum):
    """Fiscal payment object (54-ФЗ)."""

    COMMODITY = "commodity"
    EXCISE = "excise"
    JOB = "job"
    SERVICE = "service"
    GAMBLING_BET = "gambling_bet"
    GAMBLING_PRIZE = "gambling_prize"
    LOTTERY = "lottery"
    LOTTERY_PRIZE = "lottery_prize"
    INTELLECTUAL_ACTIVITY = "intellectual_activity"
    PAYMENT = "payment"
    AGENT_COMMISSION = "agent_commission"
    COMPOSITE = "composite"
    ANOTHER = "another"


class TaxType(StrEnum):
    """VAT rate / tax exemption code (54-ФЗ)."""

    NONE = "none"
    VAT0 = "vat0"
    VAT10 = "vat10"
    VAT20 = "vat20"
    VAT110 = "vat110"
    VAT120 = "vat120"
    VAT5 = "vat5"
    VAT7 = "vat7"
    VAT105 = "vat105"
    VAT107 = "vat107"


@dataclass(frozen=True, slots=True)
class RefundInvoiceItem:
    """One line item in a fiscal refund receipt.

    Only supply if you want Robokassa to emit a fiscal receipt for the refund.
    Otherwise the refund will process without a receipt (useful for refunds on
    purchases that were not fiscalized in the first place).
    """

    name: str
    quantity: int | Decimal
    cost: Decimal
    tax: TaxType = TaxType.NONE
    payment_method: PaymentMethod = PaymentMethod.FULL_PAYMENT
    payment_object: PaymentObject = PaymentObject.COMMODITY

    def to_payload(self) -> dict[str, Any]:
        """Serialize to the JSON shape expected by Robokassa JWT payload."""
        return {
            "Name": self.name,
            "Quantity": self.quantity if isinstance(self.quantity, int) else float(self.quantity),
            "Cost": float(self.cost),
            "Tax": self.tax.value,
            "PaymentMethod": self.payment_method.value,
            "PaymentObject": self.payment_object.value,
        }


@dataclass(frozen=True, slots=True)
class RefundCreateResult:
    """Response from Refund/Create."""

    success: bool
    request_id: str | None = None
    message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.success and self.request_id is not None


def build_refund_jwt(
    *,
    op_key: str,
    password3: str,
    refund_sum: Decimal | float | None = None,
    items: list[RefundInvoiceItem] | None = None,
    algorithm: JwtAlgorithm = "HS256",
) -> str:
    """Build a signed JWT for POST /Refund/Create.

    Args:
        op_key: Unique operation identifier (from OpStateExt or Result2 webhook).
        password3: Shop's Password#3 — distinct from P1 / P2.
        refund_sum: Partial refund amount. Omit (None) for full refund.
        items: Fiscal receipt items. Omit for refund without receipt.
        algorithm: One of HS256 / HS384 / HS512.

    Returns:
        Encoded JWT string ready for the POST body.
    """
    payload: dict[str, Any] = {"OpKey": op_key}
    if refund_sum is not None:
        payload["RefundSum"] = float(refund_sum)
    if items:
        payload["InvoiceItems"] = [item.to_payload() for item in items]
    # PyJWT already emits compact JSON (no whitespace) which is required.
    return jwt.encode(payload, password3, algorithm=algorithm)


def parse_refund_create_response(data: dict[str, Any]) -> RefundCreateResult:
    """Parse the JSON body returned by Refund/Create into a dataclass."""
    try:
        return RefundCreateResult(
            success=bool(data["success"]),
            request_id=data.get("requestId"),
            message=data.get("message"),
        )
    except (KeyError, TypeError) as exc:
        raise RobokassaResponseError(f"Unexpected refund response shape: {data!r}") from exc


async def refund_create(
    op_key: str,
    password3: str,
    *,
    refund_sum: Decimal | float | None = None,
    items: list[RefundInvoiceItem] | None = None,
    algorithm: JwtAlgorithm = "HS256",
    base_url: str = DEFAULT_REFUND_BASE_URL,
    http_client: httpx.AsyncClient | None = None,
    raise_on_api_error: bool = True,
) -> RefundCreateResult:
    """Initiate a refund through Robokassa's Refund API.

    Args:
        op_key: Unique operation identifier from OpStateExt or Result2.
        password3: Shop's Password#3 (requires API Refund access in cabinet).
        refund_sum: Partial refund amount. Omit for full refund.
        items: Fiscal receipt items. Omit to refund without emitting a receipt.
        algorithm: JWT algorithm (HS256 / HS384 / HS512).
        base_url: Override for the RefundService root (for testing).
        http_client: Optional pre-configured `httpx.AsyncClient`.
        raise_on_api_error: If True (default), raise `RobokassaApiError` when
            Robokassa returns `success: false`. Set False to inspect the
            message field on the returned `RefundCreateResult`.

    Returns:
        `RefundCreateResult` with `request_id` on success (used later by
        `refund_status()` / Refund/GetState) or `message` on failure.

    Raises:
        RobokassaApiError: On `success=false` when `raise_on_api_error=True`.
        RobokassaResponseError: On malformed response body.
        httpx.HTTPError: On network / HTTP-level failures.
    """
    token = build_refund_jwt(
        op_key=op_key,
        password3=password3,
        refund_sum=refund_sum,
        items=items,
        algorithm=algorithm,
    )
    url = f"{base_url}/Refund/Create"

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(
            url,
            content=token,
            headers={"Content-Type": "application/jwt"},
        )
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise RobokassaResponseError(f"Non-JSON refund response: {response.text!r}") from exc
    finally:
        if owns_client:
            await client.aclose()

    result = parse_refund_create_response(body)
    if raise_on_api_error and not result.is_success:
        raise RobokassaApiError(0, result.message or "refund_create returned success=false")
    return result


__all__ = [
    "DEFAULT_REFUND_BASE_URL",
    "JwtAlgorithm",
    "PaymentMethod",
    "PaymentObject",
    "RefundCreateResult",
    "RefundInvoiceItem",
    "RefundState",
    "TaxType",
    "build_refund_jwt",
    "parse_refund_create_response",
    "refund_create",
]
