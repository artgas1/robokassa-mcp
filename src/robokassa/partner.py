"""Robokassa Partner API — alternative refund path via partner credentials.

Partner API is a separate surface used by integrators (CPA networks, SaaS
platforms that onboard shops into Robokassa). It authenticates with
partner-level credentials (RoboxPartnerId + a JWT signed with the partner
secret), distinct from the merchant Password#1/2/3.

Most users should prefer `refund_create` (Refund API, Password#3). This
module exists for integrators who hold partner credentials.

Base URL: `https://services.robokassa.ru/PartnerRegisterService/api/`
Spec: https://docs.robokassa.ru/partner-api/MethodDescription/RefundOperation/
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import httpx

from robokassa.types import RobokassaApiError, RobokassaResponseError

PARTNER_API_BASE_URL: Final[str] = "https://services.robokassa.ru/PartnerRegisterService/api"


@dataclass(frozen=True, slots=True)
class PartnerRefundResult:
    """Response from POST /Operation/RefundOperation."""

    success: bool
    error: str | None = None
    result_code: int = 0

    @property
    def is_success(self) -> bool:
        return self.success and self.result_code == 0


def parse_partner_refund_response(data: dict[str, Any]) -> PartnerRefundResult:
    """Parse the response body from Partner API RefundOperation."""
    if "success" not in data:
        raise RobokassaResponseError(f"Unexpected partner refund response: {data!r}")
    return PartnerRefundResult(
        success=bool(data["success"]),
        error=data.get("error") or None,
        result_code=int(data.get("resultCode", 0)),
    )


async def partner_refund(
    *,
    robox_partner_id: str,
    op_key: str,
    auth_headers: dict[str, str],
    refund_sum: Decimal | float | None = None,
    receipt: list[dict[str, Any]] | None = None,
    base_url: str = PARTNER_API_BASE_URL,
    http_client: httpx.AsyncClient | None = None,
    raise_on_api_error: bool = True,
) -> PartnerRefundResult:
    """Initiate a refund via Partner API (alternative to merchant Refund API).

    Args:
        robox_partner_id: The partner's RoboxPartnerId (GUID).
        op_key: Unique operation identifier of the payment to refund.
        auth_headers: Authentication headers for the Partner API — partner
            integrations vary in their auth flow (JWT Bearer, signed
            timestamps, etc.). Caller builds them per their agreement with
            Robokassa. Typically `{"Authorization": "Bearer <partner-jwt>"}`.
        refund_sum: Amount for partial refund. Omit for full refund.
        receipt: Fiscal receipt items (list of dicts matching Robokassa's
            Partner API shape: `[{"TaxScheme": 1, "Items": [...]}, ...]`).
        base_url: Override for the Partner API root.
        http_client: Optional httpx.AsyncClient to reuse.
        raise_on_api_error: Raise `RobokassaApiError` when success=false.

    Returns:
        `PartnerRefundResult` with `{success, error, result_code}`.

    Note:
        This is the acknowledgment only. To check actual refund status,
        use other Partner API methods (not yet wrapped here).
    """
    payload: dict[str, Any] = {
        "RoboxPartnerId": robox_partner_id,
        "OpKey": op_key,
    }
    if refund_sum is not None:
        payload["RefundSum"] = float(refund_sum)
    if receipt is not None:
        payload["Receipt"] = receipt

    url = f"{base_url}/Operation/RefundOperation"
    headers = {"Content-Type": "application/json", **auth_headers}

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise RobokassaResponseError(f"Non-JSON partner refund response: {response.text!r}") from exc
    finally:
        if owns_client:
            await client.aclose()

    result = parse_partner_refund_response(body)
    if raise_on_api_error and not result.is_success:
        raise RobokassaApiError(result.result_code, result.error)
    return result


__all__ = [
    "PARTNER_API_BASE_URL",
    "PartnerRefundResult",
    "parse_partner_refund_response",
    "partner_refund",
]
