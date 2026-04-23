"""Helpers for verifying Robokassa webhook and redirect signatures.

Robokassa calls three URLs back into the merchant's system after a payment:

- **ResultURL** — server-to-server notification. Signed with Password#2.
  Expected response: ``OK<InvId>`` (case-insensitive).
- **SuccessURL** — browser redirect on successful payment. Signed with Password#1.
- **FailURL** — browser redirect on failure. No signature to verify.

For holding (StepByStep pre-auth), there is an additional ``ResultURL2`` that
carries the same signature scheme as ResultURL (Password#2).

Signature computation (all three notifications):

    signature = <algorithm>(OutSum:InvId:<password> [:Shp_key=value ... ])

Shp_ parameters are included in alphabetical order of the original name
(case-insensitive sort; Robokassa echoes them back verbatim).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from robokassa.signatures import SignatureAlgorithm, compute_signature

SHP_PREFIX = "Shp_"


def _collect_shp_parts(params: Mapping[str, Any]) -> list[str]:
    """Extract Shp_* params in alphabetical order, formatted as `Shp_key=value`.

    The comparison is case-insensitive to match Robokassa's behavior — clients
    sometimes echo keys back in a different case than the original.
    """
    shp_items: list[tuple[str, str]] = []
    for key, value in params.items():
        if key.lower().startswith(SHP_PREFIX.lower()):
            shp_items.append((key, str(value)))
    shp_items.sort(key=lambda kv: kv[0].lower())
    return [f"{k}={v}" for k, v in shp_items]


def _build_signature_parts(
    *,
    out_sum: str | float,
    inv_id: str | int,
    password: str,
    shp_params: Mapping[str, Any] | None,
) -> list[str]:
    parts: list[str] = [str(out_sum), str(inv_id), password]
    if shp_params:
        parts.extend(_collect_shp_parts(shp_params))
    return parts


def compute_result_signature(
    *,
    out_sum: str | float,
    inv_id: str | int,
    password2: str,
    shp_params: Mapping[str, Any] | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> str:
    """Compute the expected SignatureValue for a ResultURL payload.

    Formula: `<algorithm>(OutSum:InvId:Password#2[:Shp_*])`.
    """
    parts = _build_signature_parts(out_sum=out_sum, inv_id=inv_id, password=password2, shp_params=shp_params)
    return compute_signature(*parts, algorithm=algorithm)


def compute_success_signature(
    *,
    out_sum: str | float,
    inv_id: str | int,
    password1: str,
    shp_params: Mapping[str, Any] | None = None,
    algorithm: SignatureAlgorithm = "md5",
) -> str:
    """Compute the expected SignatureValue for a SuccessURL payload.

    Formula: `<algorithm>(OutSum:InvId:Password#1[:Shp_*])`.
    """
    parts = _build_signature_parts(out_sum=out_sum, inv_id=inv_id, password=password1, shp_params=shp_params)
    return compute_signature(*parts, algorithm=algorithm)


def _extract_core_params(params: Mapping[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    """Pull OutSum / InvId / SignatureValue / Shp_ from a params dict.

    Accepts keys in any case — Robokassa echoes them back as submitted and
    some downstream handlers normalize to lower-case.
    """
    out_sum: str | None = None
    inv_id: str | None = None
    signature: str | None = None
    shp_params: dict[str, Any] = {}

    for key, value in params.items():
        lower = key.lower()
        if lower == "outsum":
            out_sum = str(value)
        elif lower == "invid":
            inv_id = str(value)
        elif lower == "signaturevalue":
            signature = str(value)
        elif lower.startswith(SHP_PREFIX.lower()):
            shp_params[key] = value

    if out_sum is None or inv_id is None or signature is None:
        missing = [
            name for name, val in [("OutSum", out_sum), ("InvId", inv_id), ("SignatureValue", signature)] if val is None
        ]
        raise ValueError(f"Missing required webhook params: {missing}")

    return out_sum, inv_id, signature, shp_params


def verify_result_signature(
    params: Mapping[str, Any],
    password2: str,
    *,
    algorithm: SignatureAlgorithm = "md5",
) -> bool:
    """Verify the SignatureValue attached to a ResultURL request.

    Accepts both form-encoded dicts and query-string-style mappings. Keys are
    matched case-insensitively for `OutSum` / `InvId` / `SignatureValue`.

    Returns:
        True if the signature matches (case-insensitive hex comparison).
    """
    out_sum, inv_id, signature, shp_params = _extract_core_params(params)
    expected = compute_result_signature(
        out_sum=out_sum,
        inv_id=inv_id,
        password2=password2,
        shp_params=shp_params,
        algorithm=algorithm,
    )
    return expected.lower() == signature.lower()


def verify_success_signature(
    params: Mapping[str, Any],
    password1: str,
    *,
    algorithm: SignatureAlgorithm = "md5",
) -> bool:
    """Verify the SignatureValue attached to a SuccessURL redirect.

    Same rules as `verify_result_signature`, but signed with Password#1.
    """
    out_sum, inv_id, signature, shp_params = _extract_core_params(params)
    expected = compute_success_signature(
        out_sum=out_sum,
        inv_id=inv_id,
        password1=password1,
        shp_params=shp_params,
        algorithm=algorithm,
    )
    return expected.lower() == signature.lower()


def build_ok_response(inv_id: str | int) -> str:
    """Build the exact string Robokassa expects back on a successful ResultURL.

    Robokassa checks for `OK<InvId>` (case-insensitive) in the response body
    and retries the notification if anything else is returned.
    """
    return f"OK{inv_id}"


__all__ = [
    "build_ok_response",
    "compute_result_signature",
    "compute_success_signature",
    "verify_result_signature",
    "verify_success_signature",
]
