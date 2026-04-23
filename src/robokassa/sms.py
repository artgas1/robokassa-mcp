"""Robokassa SMS — send one-off SMS messages through the merchant account.

Endpoint: `GET https://services.robokassa.ru/SMS/`

Signature formula (per docs.robokassa.ru/ru/sms-notifications):
    MD5(login:phone:message:password1)

This is a paid service — requires a positive SMS balance in the cabinet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import httpx

from robokassa.signatures import SignatureAlgorithm, compute_signature

SMS_URL: Final[str] = "https://services.robokassa.ru/SMS/"


@dataclass(frozen=True, slots=True)
class SmsResult:
    """Response from the SMS endpoint.

    Robokassa typically returns a short textual body; callers should check
    status_code and log `body` for inspection.
    """

    status_code: int
    body: str


def build_sms_signature(
    login: str,
    phone: str,
    message: str,
    password1: str,
    *,
    algorithm: SignatureAlgorithm = "md5",
) -> str:
    """Build the signature for the SMS endpoint: hash(login:phone:message:p1)."""
    return compute_signature(login, phone, message, password1, algorithm=algorithm)


async def send_sms(
    merchant_login: str,
    phone: str,
    message: str,
    password1: str,
    *,
    sms_url: str = SMS_URL,
    algorithm: SignatureAlgorithm = "md5",
    http_client: httpx.AsyncClient | None = None,
) -> SmsResult:
    """Send an SMS via Robokassa's SMS service.

    Args:
        merchant_login: Shop identifier.
        phone: Destination number in international format (e.g. `79991234567`).
        message: SMS text. Keep within provider limits.
        password1: Shop's Password#1.
        sms_url: Override for the SMS endpoint (for testing).
        algorithm: Signature algorithm.
        http_client: Optional pre-configured client.

    Returns:
        `SmsResult` with HTTP status and response body.

    Note:
        SMS is a paid feature — the cabinet must have a non-zero SMS balance.
    """
    signature = build_sms_signature(merchant_login, phone, message, password1, algorithm=algorithm)
    params = {
        "login": merchant_login,
        "phone": phone,
        "message": message,
        "signature": signature,
    }

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.get(sms_url, params=params)
        response.raise_for_status()
        return SmsResult(status_code=response.status_code, body=response.text)
    finally:
        if owns_client:
            await client.aclose()


__all__ = [
    "SMS_URL",
    "SmsResult",
    "build_sms_signature",
    "send_sms",
]
